"""Configuration-only Signal API. Never retrieves traces or invokes a model."""

from contextlib import contextmanager
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Response
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from eval.storage import connect_database

router = APIRouter(prefix="/api/signals", tags=["Signals"])
Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def validate_schema(schema):
    if schema.get("type") != "object":
        raise ValueError("output_schema must define an object (type: object) for event payloads")
    if "$schema" in schema and not isinstance(schema["$schema"], str):
        raise ValueError("output_schema.$schema must be a JSON Schema dialect URI string")
    validator = validator_for(schema, default=Draft202012Validator if "$schema" not in schema else None)
    if validator is None:
        raise ValueError("output_schema declares an unsupported JSON Schema dialect")
    try:
        validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"Invalid output_schema: {error.message}") from error
    return schema


class CreateSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Nonblank
    description: str = ""
    instruction: Nonblank
    output_schema: dict
    enabled: bool = False

    @field_validator("output_schema")
    @classmethod
    def schema_is_valid(cls, value):
        return validate_schema(value)


class UpdateSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Nonblank | None = None
    description: str | None = None
    instruction: Nonblank | None = None
    output_schema: dict | None = None
    enabled: bool | None = None

    @field_validator("name", "description", "instruction", "output_schema", "enabled", mode="before")
    @classmethod
    def supplied_fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Omit an unchanged field instead of supplying null")
        return value

    @field_validator("output_schema")
    @classmethod
    def schema_is_valid(cls, value):
        return validate_schema(value)


@contextmanager
def database(*, read_only=False):
    try:
        with connect_database(read_only=read_only) as connection:
            yield connection
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(409, "A Signal with that name already exists.") from error
    except psycopg.errors.UndefinedTable as error:
        raise HTTPException(503, "Signal tables are missing. Apply migrations/001_signal_detection.sql.") from error
    except (psycopg.Error, ValueError, OSError) as error:
        # Do not return connection strings, database internals, or credentials.
        raise HTTPException(503, "Signal storage is unavailable. Check Postgres and DATABASE_URL.") from error


LATEST_SQL = """
SELECT s.id, s.name, s.description, s.enabled, s.created_at,
       v.version, v.instruction, v.output_schema, v.created_at AS version_created_at
FROM signals s
JOIN LATERAL (
    SELECT version, instruction, output_schema, created_at FROM signal_versions
    WHERE signal_id = s.id ORDER BY version DESC LIMIT 1
) v ON true
"""


def signal_row(connection, signal_id):
    row = connection.execute(LATEST_SQL + " WHERE s.id = %s", (signal_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Signal not found.")
    return dict(row)


@router.post("", status_code=201)
def create_signal(body: CreateSignal, response: Response):
    signal_id = uuid4()
    with database() as connection, connection.transaction():
        connection.execute("""INSERT INTO signals (id, name, description, enabled)
            VALUES (%s, %s, %s, %s)""", (signal_id, body.name, body.description, body.enabled))
        connection.execute("""INSERT INTO signal_versions (signal_id, version, instruction, output_schema)
            VALUES (%s, 1, %s, %s)""", (signal_id, body.instruction, Jsonb(body.output_schema)))
        result = signal_row(connection, signal_id)
    response.headers["Location"] = f"/api/signals/{signal_id}"
    return result


@router.get("")
def list_signals(response: Response):
    response.headers["Cache-Control"] = "no-store"
    with database(read_only=True) as connection:
        return connection.execute(LATEST_SQL + " ORDER BY s.created_at DESC, s.id").fetchall()


@router.get("/{signal_id}")
def get_signal(signal_id: UUID, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with database(read_only=True) as connection:
        return signal_row(connection, signal_id)


@router.patch("/{signal_id}")
def update_signal(signal_id: UUID, body: UpdateSignal):
    changes = body.model_dump(exclude_unset=True)
    with database() as connection, connection.transaction():
        # Serialize concurrent edits so each new version builds on the latest one.
        row = connection.execute("SELECT id FROM signals WHERE id = %s FOR UPDATE", (signal_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Signal not found.")
        current = signal_row(connection, signal_id)
        connection.execute("""UPDATE signals SET name = %s, description = %s, enabled = %s
            WHERE id = %s""", (changes.get("name", current["name"]),
                                changes.get("description", current["description"]),
                                changes.get("enabled", current["enabled"]), signal_id))
        instruction = changes.get("instruction", current["instruction"])
        schema = changes.get("output_schema", current["output_schema"])
        if instruction != current["instruction"] or schema != current["output_schema"]:
            connection.execute("""INSERT INTO signal_versions
                (signal_id, version, instruction, output_schema) VALUES (%s, %s, %s, %s)""",
                (signal_id, current["version"] + 1, instruction, Jsonb(schema)))
        return signal_row(connection, signal_id)


@router.get("/{signal_id}/versions")
def list_versions(signal_id: UUID, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with database(read_only=True) as connection:
        signal_row(connection, signal_id)
        return connection.execute("""SELECT signal_id, version, instruction, output_schema, created_at
            FROM signal_versions WHERE signal_id = %s ORDER BY version DESC""", (signal_id,)).fetchall()
