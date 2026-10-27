"""Configuration boundary checks; no external services or credentials required."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from src.core.config import Settings, get_settings


ENVIRONMENT = {
    "JWT_ISSUER": "https://identity.example.com/",
    "JWT_AUDIENCE": "enterprise-rag-api",
    "JWT_JWKS_URL": "https://identity.example.com/.well-known/jwks.json",
    "MONGODB_URI": "mongodb://user:private-password@localhost:27017",
    "CHROMA_HOST": "localhost",
    "MINIO_ENDPOINT": "localhost:9000",
    "MINIO_ACCESS_KEY": "private-access-key",
    "MINIO_SECRET_KEY": "private-secret-key",
    "REDIS_URL": "redis://:private-password@localhost:6379/0",
    "RABBITMQ_URL": "amqp://user:private-password@localhost:5672/",
    "LLM_PROVIDER": "local",
    "LLM_MODEL": "chat-model",
    "EMBEDDING_PROVIDER": "local",
    "EMBEDDING_MODEL": "embedding-model",
}


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENVIRONMENT, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def test_environment_overrides_dotenv_and_blank_optional_uses_default(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text("CHROMA_HOST=other-host\nLLM_API_KEY=\n", encoding="utf-8")
            settings = Settings(_env_file=dotenv)
        self.assertEqual(settings.chroma_host, "localhost")
        self.assertIsNone(settings.llm_api_key)
        self.assertEqual(settings.embedding_model, "embedding-model")
        with self.assertRaises(ValidationError):
            settings.chroma_host = "changed"

    def test_missing_or_malformed_configuration_fails_without_input_values(self):
        cases = (
            {"MONGODB_URI": ""},
            {"REDIS_URL": "https://private-password@localhost"},
            {"CHROMA_PORT": "65536"},
            {"MINIO_SECRET_KEY": "   "},
            {"CHROMA_HOST": "localhost:8000"},
            {"MINIO_ENDPOINT": "https://localhost:9000"},
        )
        for override in cases:
            with self.subTest(override=tuple(override)), patch.dict(os.environ, override):
                with self.assertRaises(ValidationError) as caught:
                    Settings(_env_file=None)
                self.assertNotIn("private-password", str(caught.exception))
                self.assertNotIn("input_value", str(caught.exception))

    def test_tracing_requires_complete_explicit_configuration(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, langfuse_enabled=True)
        settings = Settings(
            _env_file=None, langfuse_enabled=True,
            langfuse_public_key="public-key", langfuse_secret_key="secret-key",
            langfuse_base_url="https://traces.example.com",
        )
        self.assertTrue(settings.langfuse_enabled)

    def test_secrets_are_masked_in_repr_and_json(self):
        settings = Settings(_env_file=None)
        for secret in ("private-password", "private-access-key", "private-secret-key"):
            self.assertNotIn(secret, repr(settings))
            self.assertNotIn(secret, settings.model_dump_json())
        self.assertEqual(settings.minio_secret_key.get_secret_value(), "private-secret-key")

    def test_unknown_dotenv_variable_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text("CHROMA_POTR=8000\n", encoding="utf-8")
            with self.assertRaises(ValidationError):
                Settings(_env_file=dotenv)

    def test_jwt_configuration_requires_trusted_distinct_identity_fields(self):
        for override in (
            {"jwt_jwks_url": "http://identity.example.com/keys"},
            {"jwt_algorithm": "HS256"},
            {"jwt_tenant_id_claim": "user_id"},
            {"jwt_user_id_claim": "exp"},
        ):
            with self.subTest(fields=tuple(override)), self.assertRaises(ValidationError):
                Settings(_env_file=None, **override)

    def test_cached_loading_and_failure_logs_do_not_expose_secrets(self):
        # Run outside any local dotenv file so developer credentials cannot affect tests.
        with patch("src.core.config.Settings", side_effect=lambda: Settings(_env_file=None)):
            with self.assertLogs("src.core.config", level="DEBUG") as captured:
                first = get_settings()
                self.assertIs(first, get_settings())
            self.assertEqual(len(captured.output), 2)
            get_settings.cache_clear()
            with patch.dict(os.environ, {"REDIS_URL": "https://private-password@localhost"}):
                with self.assertLogs("src.core.config", level="ERROR") as failed:
                    with self.assertRaises(ValidationError):
                        get_settings()
            self.assertIn("redis_url", failed.output[0])
            self.assertNotIn("private-password", " ".join(captured.output + failed.output))


if __name__ == "__main__":
    unittest.main()
