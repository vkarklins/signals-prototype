-- Apply once; preserves all existing runs and findings.
BEGIN;
CREATE TABLE signal_run_reviews (
    run_id uuid PRIMARY KEY REFERENCES signal_runs(id) ON DELETE RESTRICT,
    human_label boolean NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMIT;
