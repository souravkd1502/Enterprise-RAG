"""MongoDB pool cleanup, fail-fast startup, and consistency options."""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pymongo.errors import ConnectionFailure, OperationFailure

from src.core.config import Settings
from src.infrastructure.mongodb.client import mongodb_database
from test_config import ENVIRONMENT


class MongoDBLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.dict(os.environ, ENVIRONMENT, clear=True):
            self.settings = Settings(_env_file=None)
        self.client = MagicMock()
        self.client.admin.command = AsyncMock()
        self.client.close = AsyncMock()
        self.factory = patch("src.infrastructure.mongodb.client.AsyncMongoClient", return_value=self.client)
        self.factory_mock = self.factory.start()
        self.addCleanup(self.factory.stop)
        self.indexes = patch("src.infrastructure.mongodb.client.ensure_document_indexes", new_callable=AsyncMock)
        self.indexes_mock = self.indexes.start()
        self.addCleanup(self.indexes.stop)

    async def test_startup_pings_and_closes_pool_even_if_application_fails(self):
        with self.assertRaisesRegex(RuntimeError, "application failed"):
            async with mongodb_database(self.settings) as database:
                self.assertIs(database, self.client.get_database.return_value)
                raise RuntimeError("application failed")
        self.client.admin.command.assert_awaited_once_with("ping")
        self.indexes_mock.assert_awaited_once()
        self.client.close.assert_awaited_once()
        options = self.factory_mock.call_args.kwargs
        self.assertEqual(options["timeoutMS"], 5000)
        self.assertEqual(options["maxPoolSize"], 50)
        self.assertTrue(options["tz_aware"])
        concerns = self.client.get_database.call_args.kwargs
        self.assertEqual(concerns["write_concern"].document, {"w": "majority"})

    async def test_failed_ping_is_safe_and_closes_pool(self):
        self.client.admin.command.side_effect = ConnectionFailure("credential-bearing-private-uri")
        with self.assertLogs("src.infrastructure.mongodb.client", level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, "^MongoDB initialization failed$") as caught:
                async with mongodb_database(self.settings):
                    self.fail("Unhealthy database was accepted")
        self.assertNotIn("private-uri", str(caught.exception) + " ".join(logs.output))
        self.client.close.assert_awaited_once()
        self.indexes_mock.assert_not_awaited()

    async def test_failed_index_creation_aborts_startup(self):
        self.indexes_mock.side_effect = OperationFailure("index conflict")
        with self.assertLogs("src.infrastructure.mongodb.client", level="ERROR"):
            with self.assertRaises(RuntimeError):
                async with mongodb_database(self.settings):
                    self.fail("Missing required index was accepted")
        self.client.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
