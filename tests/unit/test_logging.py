"""Logging output and identity isolation checks without running services."""

import asyncio
import io
import json
import logging
import unittest
from unittest.mock import patch

from src.core.logging import JsonFormatter, configure_logging, log_context


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        root = logging.getLogger()
        self.previous_handlers = root.handlers[:]
        self.previous_level = root.level
        # Detach test runner handlers so process startup does not close them.
        for handler in self.previous_handlers:
            root.removeHandler(handler)
        self.stdout = patch("sys.stdout", self.stream)
        self.stdout.start()
        self.addCleanup(self.stdout.stop)
        self.addCleanup(self.restore_logging)
        configure_logging()
        self.logger = logging.getLogger("tests.application_logging")

    def restore_logging(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        for handler in self.previous_handlers:
            root.addHandler(handler)
        root.setLevel(self.previous_level)

    def events(self):
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def test_json_stdout_level_and_repeated_configuration(self):
        configure_logging("WARNING")
        configure_logging("WARNING")
        self.logger.info("hidden")
        self.logger.warning("first line\nsecond line")
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message"], "first line\nsecond line")
        self.assertEqual(events[0]["level"], "WARNING")
        self.assertEqual(events[0]["logger"], self.logger.name)
        self.assertTrue(events[0]["timestamp"].endswith("+00:00"))
        self.assertIsNone(events[0]["tenant_id"])
        with self.assertRaises(ValueError):
            configure_logging("INVALID")

    def test_context_restores_after_nested_scope_and_exception(self):
        with log_context(tenant_id="tenant-a", user_id="user-a", request_id="request-a"):
            self.logger.info("outer", extra={"tenant_id": "spoofed", "body": "private"})
            with self.assertRaises(RuntimeError):
                with log_context(tenant_id="tenant-b"):
                    self.logger.info("inner")
                    raise RuntimeError("stop")
            self.logger.info("restored")
        self.logger.info("outside")
        outer, inner, restored, outside = self.events()
        self.assertEqual(outer["tenant_id"], "tenant-a")
        self.assertNotIn("body", outer)
        self.assertEqual(inner["tenant_id"], "tenant-b")
        self.assertIsNone(inner["user_id"])
        self.assertIsNone(inner["request_id"])
        self.assertEqual(restored["user_id"], "user-a")
        self.assertIsNone(outside["tenant_id"])

    def test_concurrent_requests_keep_separate_tenant_contexts(self):
        async def request(tenant):
            with log_context(tenant_id=tenant, user_id=tenant + "-user"):
                await asyncio.sleep(0)
                self.logger.info("request %s", tenant)

        async def run():
            await asyncio.gather(request("tenant-a"), request("tenant-b"))

        asyncio.run(run())
        for event in self.events():
            self.assertEqual(event["message"], "request " + event["tenant_id"])
            self.assertEqual(event["user_id"], event["tenant_id"] + "-user")

    def test_context_rejects_invalid_identifiers(self):
        for values in (
            {"tenant_id": ""}, {"tenant_id": "a\nb"}, {"tenant_id": "a" * 257},
            {"tenant_id": 12}, {"user_id": "user-without-tenant"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                with log_context(**values):
                    self.fail("Invalid identifiers were accepted")

    def test_message_redaction_handles_interpolation_and_common_credentials(self):
        examples = (
            "Authorization: Bearer private-token",
            "Authorization: Basic cHJpdmF0ZQ==",
            "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.private-signature",
            "mongodb://user:private-password@localhost/db",
            'api_key="private-key with spaces"',
            "{'password': 'private-password'}",
            "LLM_API_KEY=private-key",
            "https://host/path?token=private-token&safe=yes",
        )
        for message in examples:
            self.logger.info("operation %s", message)
        self.assertEqual(len(self.events()), len(examples))
        for event in self.events():
            self.assertNotIn("private", event["message"])
            self.assertIn("[REDACTED]", event["message"])

    def test_exceptions_exclude_messages_and_frame_source(self):
        try:
            raise RuntimeError("unlabelled-sensitive-document-content")
        except RuntimeError:
            self.logger.exception("Processing failed")
        event = self.events()[0]
        self.assertEqual(event["exception"]["type"], "RuntimeError")
        self.assertTrue(event["exception"]["frames"])
        self.assertNotIn("unlabelled-sensitive", self.stream.getvalue())
        self.assertNotIn("message", event["exception"])

    def test_formatting_does_not_mutate_original_record(self):
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "token=%s", ("private",), None)
        original = record.__dict__.copy()
        JsonFormatter().format(record)
        self.assertEqual(record.__dict__, original)


if __name__ == "__main__":
    unittest.main()
