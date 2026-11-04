-- Signals prototype: database schema (Postgres 12+).
-- One file for both tracks; see docs/CONTRACT.md (v1.1).
--   turns    Track A (sync) writes one row per turn item; Track B reads it.
--   results  Track B stores one probability per turn, signal, and question version.
--   signals / signal_versions  Configurable detector definitions (future engine).
--   signal_runs / signal_events  Analysis records and structured findings.
--
-- Apply to a fresh database:  psql -d <database> -f schema.sql

-- ---------------------------------------------------------------- turns (Track A)

CREATE TABLE turns (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 'live' = synced from Laminar; 'gold' = loaded from eval/gold/*.jsonl.
    source          text NOT NULL CHECK (source IN ('live', 'gold')),

    -- The turn item exactly as in docs/CONTRACT.md: the target turn plus up to
    -- 10 earlier turns. This is what the classifier reads. Rows never change.
    item            jsonb NOT NULL
                        CONSTRAINT turns_item_contract_v1 CHECK (item ->> 'contract' = 'v1'),

    -- Computed from item by Postgres, so they can never disagree with it.
    -- The target is always the last element of item.turns (-1 = last).
    trace_id        uuid GENERATED ALWAYS AS
                        ((item -> 'turns' -> -1 ->> 'trace_id')::uuid) STORED,
    conversation_id text NOT NULL GENERATED ALWAYS AS
                        (item ->> 'conversation_id') STORED,
    target_index    integer NOT NULL GENERATED ALWAYS AS
                        ((item ->> 'target_turn')::integer) STORED,

    -- Gold rows only: the gold file's case_id, to join results to the labels.
    gold_case_id    text,

    -- Live rows only: the root span's end_time in Laminar.
    -- The polling marker is max(turn_ended_at) over live rows.
    turn_ended_at   timestamptz,

    created_at      timestamptz NOT NULL DEFAULT now(),

    -- Dedupe: a turn is written once. UNIQUE allows any number of NULLs,
    -- so gold rows (trace_id NULL) are fine.
    CONSTRAINT turns_trace_id_key UNIQUE (trace_id),
    CONSTRAINT turns_gold_case_id_key UNIQUE (gold_case_id),

    -- A live row without a trace_id would slip past the dedupe silently,
    -- and one without turn_ended_at would be invisible to the marker.
    CONSTRAINT turns_live_fields CHECK (
        source <> 'live'
        OR (trace_id IS NOT NULL AND turn_ended_at IS NOT NULL AND gold_case_id IS NULL)
    ),
    CONSTRAINT turns_gold_fields CHECK (
        source <> 'gold'
        OR (gold_case_id IS NOT NULL AND turn_ended_at IS NULL)
    )
);

-- For the polling marker: SELECT max(turn_ended_at) FROM turns WHERE source = 'live';
CREATE INDEX turns_live_ended_at_idx ON turns (turn_ended_at) WHERE source = 'live';

-- ---------------------------------------------------------------- results (Track B)

CREATE TABLE results (
    turn_id          bigint NOT NULL REFERENCES turns(id),
    signal           text NOT NULL,
    question_version text NOT NULL,
    probability      real NOT NULL CHECK (probability BETWEEN 0 AND 1),

    -- Keep one score for each signal/question version on each turn.
    CONSTRAINT results_turn_signal_question_key
        PRIMARY KEY (turn_id, signal, question_version)
);


-- Configurable Signal detection (mirrors migrations/001_signal_detection.sql).

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

-- Human judgments of whether a Signal applies to its target turn.
CREATE TABLE signal_run_reviews (
    run_id uuid PRIMARY KEY REFERENCES signal_runs(id) ON DELETE RESTRICT,
    human_label boolean NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
