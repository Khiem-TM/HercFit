"""Core regression tests without credentials, network calls, or a running database."""

import importlib
import os
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import SecretStr, ValidationError

# Import the public package without reading the developer's .env or environment.
with (
    patch.dict(os.environ, {}, clear=True),
    patch("pydantic_settings.sources.DotEnvSettingsSource.__call__", return_value={}),
):
    import core
    from core.settings import Settings
    from schema import ServiceMetadata, UserInput

llm = importlib.import_module("core.llm")
database = importlib.import_module("core.database")
observability = importlib.import_module("core.observability")


def config(**overrides):
    with patch.dict(os.environ, {}, clear=True):
        return Settings(_env_file=None, **overrides)


class SettingsTests(unittest.TestCase):
    def test_public_imports_are_preserved(self):
        self.assertIs(core.get_model, llm.get_model)
        self.assertIs(core.get_db, database.get_db)

    def test_configuration_can_load_before_model_key_is_added(self):
        settings = config()
        self.assertIsNone(settings.MODEL_API_KEY)
        self.assertEqual(settings.POSTGRES_HOST, "localhost")
        self.assertEqual(settings.DATABASE_TYPE, "postgres")
        self.assertEqual(settings.AVAILABLE_MODELS, {settings.DEFAULT_MODEL})
        self.assertTrue(settings.PGVECTOR_ENABLED)

    def test_legacy_model_and_langsmith_names(self):
        settings = config(
            OPENAI_API_KEY="model-test-key",
            COMPATIBLE_BASE_URL="https://provider.example/v1/",
            COMPATIBLE_MODEL="provider/custom-model",
            LANGCHAIN_TRACING_V2=True,
            LANGCHAIN_API_KEY="trace-test-key",
        )
        self.assertEqual(settings.MODEL_API_KEY.get_secret_value(), "model-test-key")
        self.assertEqual(settings.DEFAULT_MODEL, "provider/custom-model")
        self.assertEqual(settings.MODEL_BASE_URL, "https://provider.example/v1")
        self.assertTrue(settings.LANGSMITH_TRACING)
        self.assertNotIn("model-test-key", repr(settings))

    def test_new_key_takes_precedence_over_legacy_key(self):
        settings = config(MODEL_API_KEY="new", OPENAI_API_KEY="legacy")
        self.assertEqual(settings.MODEL_API_KEY.get_secret_value(), "new")

    def test_invalid_configuration_is_rejected(self):
        invalid = [
            {"DATABASE_TYPE": "sqlite"},
            {"DATABASE_TYPE": "mongo"},
            {"MODEL_BASE_URL": "not-a-url"},
            {"POSTGRES_PORT": 0},
            {"POSTGRES_MIN_CONNECTIONS_PER_POOL": 5, "POSTGRES_MAX_CONNECTIONS_PER_POOL": 1},
            {"LANGSMITH_TRACING": True},
            {"EMBEDDING_MODEL": "embedding-model", "PGVECTOR_ENABLED": False},
            {"DEFAULT_MODEL": "fake"},
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                config(**values)

    def test_fake_mode_is_explicit_and_published_consistently(self):
        settings = config(USE_FAKE_MODEL=True, MODEL_API_KEY="unused")
        self.assertEqual(settings.DEFAULT_MODEL, "fake")
        self.assertEqual(settings.AVAILABLE_MODELS, {"fake"})

    def test_custom_model_roundtrips_through_api_schemas(self):
        model = "provider/custom-model"
        self.assertEqual(UserInput(message="hello", model=model).model, model)
        metadata = ServiceMetadata(
            agents=[], models=[model], default_model=model, default_agent="test"
        )
        self.assertEqual(metadata.model_dump()["default_model"], model)


class ModelTests(unittest.TestCase):
    def tearDown(self):
        llm.get_model.cache_clear()
        llm.get_embeddings.cache_clear()

    def test_missing_key_fails_at_model_creation(self):
        with (
            patch.object(llm, "settings", config()),
            self.assertRaisesRegex(ValueError, "MODEL_API_KEY"),
        ):
            llm.get_model()

    def test_custom_endpoint_receives_the_only_model_key(self):
        settings = config(
            MODEL_API_KEY="one-key",
            MODEL_BASE_URL="https://provider.example/v1",
            DEFAULT_MODEL="provider/model",
        )
        with patch.object(llm, "settings", settings), patch.object(llm, "ChatOpenAI") as factory:
            first = llm.get_model("provider/model")
            self.assertIs(first, llm.get_model("provider/model"))
            factory.assert_called_once()
            self.assertEqual(factory.call_args.kwargs["api_key"].get_secret_value(), "one-key")
            self.assertEqual(factory.call_args.kwargs["base_url"], settings.MODEL_BASE_URL)
            with self.assertRaisesRegex(ValueError, "not configured"):
                llm.get_model("another-model")

    def test_real_client_can_be_constructed_without_network(self):
        settings = config(MODEL_API_KEY="test-only", DEFAULT_MODEL="provider/model")
        with patch.object(llm, "settings", settings):
            model = llm.get_model()
        self.assertEqual(model.model_name, "provider/model")
        self.assertEqual(model.openai_api_key.get_secret_value(), "test-only")

    def test_fake_model_runs_without_api_key(self):
        with patch.object(llm, "settings", config(USE_FAKE_MODEL=True)):
            model = llm.get_model("fake")
            self.assertIn("test response", model.invoke("hello").content)
            self.assertIs(model.bind_tools([]), model)

    def test_embeddings_reuse_the_same_key_and_endpoint(self):
        settings = config(MODEL_API_KEY="one-key", EMBEDDING_MODEL="test-embedding")
        with patch.object(llm, "settings", settings):
            embeddings = llm.get_embeddings()
        self.assertEqual(embeddings.openai_api_key.get_secret_value(), "one-key")
        self.assertEqual(embeddings.openai_api_base, settings.MODEL_BASE_URL)


class TracingTests(unittest.TestCase):
    def tearDown(self):
        observability.get_langsmith_client.cache_clear()

    def test_disabled_tracing_creates_no_client(self):
        with (
            patch.object(observability, "settings", config()),
            patch.object(observability, "Client") as client,
        ):
            self.assertEqual(observability.get_tracing_callbacks(), [])
            client.assert_not_called()

    def test_callback_uses_explicit_project_key_and_endpoint(self):
        settings = config(LANGSMITH_TRACING=True, LANGSMITH_API_KEY="trace-key")
        with (
            patch.object(observability, "settings", settings),
            patch.object(observability, "Client") as client,
            patch.object(observability, "LangChainTracer") as tracer,
        ):
            self.assertEqual(observability.get_tracing_callbacks(), [tracer.return_value])
            client.assert_called_once_with(api_url=settings.LANGSMITH_ENDPOINT, api_key="trace-key")
            tracer.assert_called_once_with(
                project_name=settings.LANGSMITH_PROJECT, client=client.return_value
            )


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool_patch = patch.object(database, "_crud_pool", None)
        self.pool_patch.start()
        self.addCleanup(self.pool_patch.stop)

    async def test_connection_before_initialization_raises(self):
        with self.assertRaisesRegex(RuntimeError, "not initialized"):
            async with database.get_db_connection():
                self.fail("Uninitialized pool must not yield a connection")

    async def test_dsn_handles_special_characters(self):
        from psycopg.conninfo import conninfo_to_dict

        password = "p@ss:/?# with 'quotes' and \\slashes"
        with patch.object(database, "settings", config(POSTGRES_PASSWORD=SecretStr(password))):
            parsed = conninfo_to_dict(database.get_postgres_connection_string())
        self.assertEqual(parsed["password"], password)
        self.assertEqual(parsed["host"], "localhost")

    async def test_pool_readiness_extension_and_idempotent_shutdown(self):
        connection = AsyncMock()
        pool = MagicMock(open=AsyncMock(), close=AsyncMock())
        pool.connection.return_value.__aenter__.return_value = connection
        with (
            patch.object(database, "settings", config()),
            patch.object(database, "AsyncConnectionPool", return_value=pool) as factory,
        ):
            await database.init_crud_db_pool()
            await database.init_crud_db_pool()
            factory.assert_called_once()
            pool.open.assert_awaited_once_with(wait=True, timeout=30)
            connection.execute.assert_awaited_once_with("CREATE EXTENSION IF NOT EXISTS vector")
            await database.close_crud_db_pool()
            await database.close_crud_db_pool()
            pool.close.assert_awaited_once()
            self.assertIsNone(database._crud_pool)

    async def test_failed_pool_open_closes_pool(self):
        pool = MagicMock(open=AsyncMock(side_effect=RuntimeError("unavailable")), close=AsyncMock())
        with patch.object(database, "AsyncConnectionPool", return_value=pool):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                await database.init_crud_db_pool()
            pool.close.assert_awaited_once()
            self.assertIsNone(database._crud_pool)

    async def test_failed_extension_setup_closes_pool(self):
        connection = AsyncMock()
        connection.execute.side_effect = RuntimeError("extension unavailable")
        pool = MagicMock(open=AsyncMock(), close=AsyncMock())
        pool.connection.return_value.__aenter__.return_value = connection
        with (
            patch.object(database, "settings", config()),
            patch.object(database, "AsyncConnectionPool", return_value=pool),
        ):
            with self.assertRaisesRegex(RuntimeError, "extension unavailable"):
                await database.init_crud_db_pool()
            pool.close.assert_awaited_once()
            self.assertIsNone(database._crud_pool)

    async def test_error_propagates_to_connection_transaction_context(self):
        pool = MagicMock()
        pool.connection.return_value.__aexit__.return_value = False
        with (
            patch.object(database, "_crud_pool", pool),
            self.assertRaisesRegex(ValueError, "rollback"),
        ):
            async with database.get_db_connection():
                raise ValueError("rollback")
        self.assertIs(pool.connection.return_value.__aexit__.call_args.args[0], ValueError)


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_only_imports_and_optional_vector_index(self):
        memory = importlib.import_module("memory.postgres")

        @asynccontextmanager
        async def pool(_component):
            yield MagicMock()

        for embedding_model in (None, "test-embedding"):
            settings = config(EMBEDDING_MODEL=embedding_model)
            store = MagicMock(setup=AsyncMock())
            with (
                patch.object(memory, "settings", settings),
                patch.object(memory, "_memory_pool", pool),
                patch.object(memory, "get_embeddings", return_value="embedding-object"),
                patch.object(memory, "AsyncPostgresStore", return_value=store) as factory,
            ):
                async with memory.get_postgres_store() as actual:
                    self.assertIs(actual, store)
                expected = (
                    None if embedding_model is None else {"dims": 1536, "embed": "embedding-object"}
                )
                self.assertEqual(factory.call_args.kwargs["index"], expected)
                store.setup.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
