"""Signal configuration behavior; synthetic inputs and disposable schemas only."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient

from backend.app import app
from eval.storage import connect_database

ROOT = Path(__file__).resolve().parents[1]


def definition(**changes):
    return {"name": "Failure detector", "description": "Finds significant errors",
            "instruction": "Find significant mistakes; ignore corrected slips.",
            "output_schema": {"type": "object", "properties": {"issue_type": {"type": "string"}},
                              "required": ["issue_type"], "additionalProperties": False}, **changes}


class SignalValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.db = self.enterContext(patch("backend.signals.connect_database"))

    def test_invalid_input_never_opens_database(self):
        for change in ({"name": " "}, {"instruction": ""}, {"description": None},
                       {"enabled": "true"}, {"output_schema": []},
                       {"output_schema": {"type": "array"}},
                       {"output_schema": {"type": "object", "required": "issue"}},
                       {"output_schema": {"type": "object", "properties": {"issue": {"type": "invalid"}}}},
                       {"output_schema": {"type": "object", "$schema": "https://unknown.invalid/schema"}},
                       {"output_schema": {"type": "object", "$schema": []}},
                       {"model": "not-configurable"}):
            with self.subTest(change=change):
                self.assertEqual(self.client.post("/api/signals", json=definition(**change)).status_code, 422)
        self.db.assert_not_called()

    def test_patch_nulls_unknown_fields_and_invalid_ids(self):
        for key in ("name", "description", "instruction", "output_schema", "enabled"):
            self.assertEqual(self.client.patch(f"/api/signals/{uuid4()}", json={key: None}).status_code, 422)
        self.assertEqual(self.client.patch(f"/api/signals/{uuid4()}", json={"version": 3}).status_code, 422)
        self.assertEqual(self.client.get("/api/signals/not-a-uuid").status_code, 422)
        self.db.assert_not_called()

    def test_storage_errors_are_actionable_and_hide_credentials(self):
        for error, expected in [(psycopg.errors.UndefinedTable("internal table"), "001_signal_detection.sql"),
                                (psycopg.OperationalError("password=secret"), "storage is unavailable"),
                                (ValueError("password=secret"), "storage is unavailable")]:
            with self.subTest(error=error):
                self.db.side_effect = error
                response = self.client.get("/api/signals")
                self.assertEqual(response.status_code, 503)
                self.assertIn(expected, response.json()["detail"])
                self.assertNotIn("secret", response.text)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL for Postgres checks")
class SignalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "signals_api_" + uuid4().hex
        admin = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)
        cls.addClassCleanup(admin.close)
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.addClassCleanup(admin.execute, sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))
        cls.url = make_conninfo(os.environ["TEST_DATABASE_URL"], options=f"-c search_path={cls.schema}")
        with psycopg.connect(cls.url, autocommit=True) as conn:
            conn.execute((ROOT / "schema.sql").read_text())

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"DATABASE_URL": self.url}))
        self.enterContext(patch("openai.OpenAI", side_effect=AssertionError("No model calls allowed")))
        self.conn = self.enterContext(connect_database())
        self.conn.execute("TRUNCATE signal_events, signal_runs, signal_versions, signals")
        self.client = TestClient(app)

    def create(self, **changes):
        response = self.client.post("/api/signals", json=definition(**changes))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_defaults_and_latest_definition(self):
        created = self.create(name="  Failure detector  ")
        self.assertEqual(created["name"], "Failure detector")
        self.assertFalse(created["enabled"])
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["output_schema"], definition()["output_schema"])
        self.assertEqual(self.client.get(f'/api/signals/{created["id"]}').json(), created)
        self.assertEqual(self.client.get('/api/signals').json(), [created])
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM signal_runs").fetchone()["n"], 0)

    def test_metadata_toggle_and_unchanged_configuration_preserve_version(self):
        created = self.create()
        url = f'/api/signals/{created["id"]}'
        for changes in ({"description": "Updated", "name": "Renamed", "enabled": True},
                        {"instruction": created["instruction"], "output_schema": created["output_schema"]},
                        {}, {"enabled": False}):
            response = self.client.patch(url, json=changes)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["version"], 1)
        versions = self.client.get(url + '/versions').json()
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["instruction"], created["instruction"])

    def test_changes_create_versions_without_overwriting_history(self):
        created = self.create()
        url = f'/api/signals/{created["id"]}'
        self.assertEqual(self.client.patch(url, json={"instruction": "Find wrong actions"}).json()["version"], 2)
        schema = {"type": "object", "properties": {"action": {"type": "string"}}}
        latest = self.client.patch(url, json={"instruction": "Find unsupported actions", "output_schema": schema}).json()
        self.assertEqual(latest["version"], 3)
        history = self.client.get(url + '/versions').json()
        self.assertEqual([v["version"] for v in history], [3, 2, 1])
        self.assertEqual(history[-1]["instruction"], created["instruction"])
        self.assertEqual(history[-1]["output_schema"], created["output_schema"])
        self.assertEqual(self.client.get('/api/signals').json()[0], latest)

    def test_conflicts_and_missing_records(self):
        first = self.create()
        second = self.create(name="Another")
        self.assertEqual(self.client.post('/api/signals', json=definition()).status_code, 409)
        response = self.client.patch(f'/api/signals/{second["id"]}', json={"name": first["name"], "instruction": "Changed"})
        self.assertEqual(response.status_code, 409)
        unchanged = self.client.get(f'/api/signals/{second["id"]}').json()
        self.assertEqual((unchanged["name"], unchanged["version"]), ("Another", 1))
        for suffix in ('', '/versions'):
            self.assertEqual(self.client.get(f'/api/signals/{uuid4()}{suffix}').status_code, 404)
        self.assertEqual(self.client.patch(f'/api/signals/{uuid4()}', json={"enabled": True}).status_code, 404)

    def test_create_and_update_rollback_on_version_write_failure(self):
        self.conn.execute("ALTER TABLE signal_versions ADD CONSTRAINT reject_test CHECK (instruction <> 'rejected')")
        try:
            self.assertEqual(self.client.post('/api/signals', json=definition(instruction="rejected")).status_code, 503)
            self.assertEqual(self.client.get('/api/signals').json(), [])
            created = self.create()
            url = f'/api/signals/{created["id"]}'
            response = self.client.patch(url, json={"name": "Should roll back", "instruction": "rejected"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(self.client.get(url).json(), created)
        finally:
            self.conn.execute("ALTER TABLE signal_versions DROP CONSTRAINT reject_test")

    def test_read_endpoints_use_read_only_connections(self):
        created = self.create()
        with patch("backend.signals.connect_database", wraps=connect_database) as factory:
            for path in ('/api/signals', f'/api/signals/{created["id"]}', f'/api/signals/{created["id"]}/versions'):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertTrue(all(call.kwargs == {"read_only": True} for call in factory.call_args_list))

    def test_concurrent_updates_have_distinct_versions(self):
        created = self.create()
        url = f'/api/signals/{created["id"]}'
        def update(instruction):
            with TestClient(app) as client:
                return client.patch(url, json={"instruction": instruction})
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(update, ['Instruction A', 'Instruction B']))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        versions = self.client.get(url + '/versions').json()
        self.assertEqual([v['version'] for v in versions], [3, 2, 1])
        self.assertEqual({v['instruction'] for v in versions[:2]}, {'Instruction A', 'Instruction B'})


if __name__ == '__main__':
    unittest.main()
