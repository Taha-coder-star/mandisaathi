-- Task 6.2 (RFC C3, §8; file 06 §4): the conversation tables the orchestrator skeleton writes. Choices: DECISIONS.md D-028.
-- query_patch_log, answer_shown, pending_clarification come with 7.2; message_log with its first writer (9.1/11.2).

CREATE TABLE wa_user (
    user_key        text PRIMARY KEY,                    -- same key as inbound_event.user_key: BSUID or hashed number
    consent_at      timestamptz NOT NULL,                -- consent + AI disclosure shown on first contact (file 07 §3)
    last_inbound_at timestamptz,                         -- service window = last_inbound_at + 24 h
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE query_state (
    user_key   text PRIMARY KEY REFERENCES wa_user ON DELETE CASCADE,
    state      jsonb NOT NULL DEFAULT '{}',              -- slots and provenance: task 7.2
    version    integer NOT NULL DEFAULT 0,               -- +1 per turn
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- STOP keeps only an anonymous message count (file 06 §3): no user key, no text.
CREATE TABLE stop_tally (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stopped_on    date NOT NULL DEFAULT current_date,
    message_count integer NOT NULL
);

-- The turn job that took this message (coalescing): a retried turn re-reads its own messages, no other job can take them.
ALTER TABLE inbound_event ADD COLUMN turn_job_id bigint;
CREATE INDEX inbound_event_turn ON inbound_event (turn_job_id) WHERE turn_job_id IS NOT NULL;

-- Messages from before 6.2 were already answered by the echo bot; without this the first new turn would sweep them in.
UPDATE inbound_event SET processed_at = received_at WHERE processed_at IS NULL;
