"""DDL checks using isolated schemas in TEST_DATABASE_URL; never call an LLM."""

import os
from pathlib import Path
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / "schema.sql").read_text()
BASELINE = SCHEMA.split("-- Configurable Signal detection", 1)[0]
MIGRATION = (ROOT / "migrations/001_signal_detection.sql").read_text()


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL for Postgres checks")
class SignalSchemaTests(unittest.TestCase):
    def database(self, ddl):
        namespace = "signals_ddl_" + uuid4().hex
        admin = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)
        self.addCleanup(admin.close)
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
        self.addCleanup(admin.execute, sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(namespace)))
        connection = psycopg.connect(make_conninfo(
            os.environ["TEST_DATABASE_URL"], options=f"-c search_path={namespace}"
        ), autocommit=True)
        self.addCleanup(connection.close)
        connection.execute(ddl)
        return connection

    def setUp(self):
        self.conn = self.database(SCHEMA)
        self.turn = self.add_turn(self.conn)
        self.signal, self.run = uuid4(), uuid4()
        self.conn.execute("INSERT INTO signals (id, name) VALUES (%s, 'Failure detector')", (self.signal,))
        self.conn.execute("INSERT INTO signal_versions VALUES (%s, 1, 'Find failures', %s, now())",
                          (self.signal, Jsonb({"type": "object"})))
        self.conn.execute("""INSERT INTO signal_runs (id, turn_id, signal_id, signal_version, model)
                             VALUES (%s, %s, %s, 1, 'test-model')""", (self.run, self.turn, self.signal))

    def add_turn(self, connection):
        item = {"contract": "v1", "conversation_id": "test", "target_turn": 1,
                "turns": [{"trace_id": None}]}
        return connection.execute("""INSERT INTO turns (source, item, gold_case_id)
            VALUES ('gold', %s, 'schema-case') RETURNING id""", (Jsonb(item),)).fetchone()[0]

    def event(self, ids=None, severity="warning", payload=None):
        self.conn.execute("""INSERT INTO signal_events
            (id, run_id, summary, severity, evidence, supporting_span_ids, payload)
            VALUES (%s, %s, 'Booking claim unsupported', %s, 'Tool returned failure', %s, %s)""",
            (uuid4(), self.run, severity, ids, Jsonb({} if payload is None else payload)))

    def test_null_span_ids_and_multiple_events(self):
        self.event()
        self.event([uuid4()])
        rows = self.conn.execute("SELECT supporting_span_ids FROM signal_events").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIn((None,), rows)

    def test_invalid_events_rejected(self):
        for kwargs in ({"ids": []}, {"ids": [None]}, {"severity": "urgent"}, {"payload": []}):
            with self.subTest(kwargs=kwargs), self.assertRaises(psycopg.errors.CheckViolation):
                self.event(**kwargs)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute("""INSERT INTO signal_events
                (id, run_id, summary, severity, evidence, payload)
                VALUES (%s, %s, ' ', 'info', 'evidence', '{}')""", (uuid4(), self.run))

    def test_duplicate_runs_and_missing_versions_rejected(self):
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.conn.execute("""INSERT INTO signal_runs (id, turn_id, signal_id, signal_version, model)
                VALUES (%s, %s, %s, 1, 'test')""", (uuid4(), self.turn, self.signal))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.conn.execute("""INSERT INTO signal_runs (id, turn_id, signal_id, signal_version, model)
                VALUES (%s, %s, %s, 99, 'test')""", (uuid4(), self.turn, self.signal))

    def test_status_and_completion_rules(self):
        for assignment in ("status = 'unknown'", "status = 'succeeded', finished_at = now()",
                           "status = 'failed'", "finished_at = now()",
                           "input_snapshot = '[]'::jsonb"):
            with self.subTest(assignment=assignment), self.assertRaises(psycopg.errors.CheckViolation):
                self.conn.execute(f"UPDATE signal_runs SET {assignment} WHERE id = %s", (self.run,))
        self.conn.execute("""UPDATE signal_runs SET status = 'succeeded',
            input_snapshot = '{}', finished_at = now() WHERE id = %s""", (self.run,))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM signal_events").fetchone()[0], 0)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute("UPDATE signal_runs SET error = 'failed' WHERE id = %s", (self.run,))

    def test_identity_version_and_delete_constraints(self):
        for statement, params, error in [
            ("INSERT INTO signals (id, name) VALUES (%s, 'Failure detector')", (uuid4(),), psycopg.errors.UniqueViolation),
            ("INSERT INTO signals (id, name) VALUES (%s, ' ')", (uuid4(),), psycopg.errors.CheckViolation),
            ("INSERT INTO signal_versions VALUES (%s, 0, 'Detect', '{}', now())", (self.signal,), psycopg.errors.CheckViolation),
            ("INSERT INTO signal_versions VALUES (%s, 2, 'Detect', '[]', now())", (self.signal,), psycopg.errors.CheckViolation),
            ("DELETE FROM signals WHERE id = %s", (self.signal,), psycopg.errors.ForeignKeyViolation),
            ("DELETE FROM turns WHERE id = %s", (self.turn,), psycopg.errors.ForeignKeyViolation),
        ]:
            with self.subTest(statement=statement), self.assertRaises(error):
                self.conn.execute(statement, params)
        self.event()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.conn.execute("DELETE FROM signal_runs WHERE id = %s", (self.run,))

    def catalog(self, connection):
        columns = connection.execute("""SELECT table_name, column_name, data_type, udt_name,
            is_nullable, column_default FROM information_schema.columns
            WHERE table_schema = current_schema() ORDER BY table_name, ordinal_position""").fetchall()
        constraints = connection.execute("""SELECT c.relname, con.conname, pg_get_constraintdef(con.oid)
            FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = current_schema()
            ORDER BY c.relname, con.conname""").fetchall()
        indexes = connection.execute("""SELECT tablename, indexname, replace(indexdef, schemaname, 'test_schema')
            FROM pg_indexes WHERE schemaname = current_schema() ORDER BY indexname""").fetchall()
        return columns, constraints, indexes

    def test_migration_matches_fresh_install_and_preserves_existing_data(self):
        upgraded = self.database(BASELINE)
        turn = self.add_turn(upgraded)
        upgraded.execute("INSERT INTO results VALUES (%s, 'user_frustration', 'v1', 0.75)", (turn,))
        before = upgraded.execute("SELECT * FROM turns").fetchall()
        upgraded.execute(MIGRATION)
        self.assertEqual(upgraded.execute("SELECT * FROM turns").fetchall(), before)
        self.assertEqual(upgraded.execute("SELECT probability FROM results").fetchone()[0], 0.75)
        self.assertEqual(self.catalog(self.conn), self.catalog(upgraded))

    def test_migration_failure_is_atomic(self):
        upgraded = self.database(BASELINE)
        self.add_turn(upgraded)
        upgraded.execute("CREATE TABLE signal_versions (placeholder integer)")
        with self.assertRaises(psycopg.errors.DuplicateTable):
            upgraded.execute(MIGRATION)
        upgraded.execute("ROLLBACK")
        self.assertIsNone(upgraded.execute("SELECT to_regclass('signals')").fetchone()[0])
        self.assertEqual(upgraded.execute("SELECT count(*) FROM turns").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
