-- Apply once to an existing database that already has turns and results.
-- This migration is also mirrored in schema.sql for fresh installations.
BEGIN;

CREATE TABLE signals (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE CHECK (length(btrim(name)) > 0),
    description text NOT NULL DEFAULT '',
    enabled boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Versions are immutable by application convention; no update trigger is installed.
-- The greatest version number is the active configuration for an enabled signal.
CREATE TABLE signal_versions (
    signal_id uuid NOT NULL REFERENCES signals(id) ON DELETE RESTRICT,
    version integer NOT NULL CHECK (version > 0),
    instruction text NOT NULL CHECK (length(btrim(instruction)) > 0),
    output_schema jsonb NOT NULL CHECK (jsonb_typeof(output_schema) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (signal_id, version)
);

CREATE TABLE signal_runs (
    id uuid PRIMARY KEY,
    turn_id bigint NOT NULL REFERENCES turns(id) ON DELETE RESTRICT,
    signal_id uuid NOT NULL,
    signal_version integer NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    model text NOT NULL CHECK (length(btrim(model)) > 0),
    input_snapshot jsonb CHECK (jsonb_typeof(input_snapshot) = 'object'),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    FOREIGN KEY (signal_id, signal_version)
        REFERENCES signal_versions(signal_id, version) ON DELETE RESTRICT,
    UNIQUE (turn_id, signal_id, signal_version),
    CONSTRAINT signal_runs_completion CHECK (
        (status IN ('pending', 'running') AND finished_at IS NULL)
        OR (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL)
    ),
    CONSTRAINT signal_runs_success CHECK (
        status <> 'succeeded' OR (input_snapshot IS NOT NULL AND error IS NULL)
    )
);

CREATE INDEX signal_runs_status_created_idx ON signal_runs (status, created_at);

CREATE TABLE signal_events (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES signal_runs(id) ON DELETE RESTRICT,
    summary text NOT NULL CHECK (length(btrim(summary)) > 0),
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    evidence text NOT NULL CHECK (length(btrim(evidence)) > 0),
    -- NULL supports events produced before span citations are available.
    supporting_span_ids uuid[],
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT signal_events_span_ids CHECK (
        supporting_span_ids IS NULL
        OR (cardinality(supporting_span_ids) > 0
            AND array_position(supporting_span_ids, NULL) IS NULL)
    )
);

CREATE INDEX signal_events_run_idx ON signal_events (run_id);

-- Application responsibilities: validate JSON Schema and event payloads, verify
-- cited spans against input_snapshot, and atomically save events + run success.
-- Signal, run and event UUIDs are supplied by the application.
COMMIT;
