-- Task 7.2 (RFC C7, §8; file 06 §4–5): the query state manager's tables. Choices: DECISIONS.md D-032.
-- Every table references wa_user ON DELETE CASCADE, so STOP (handlers._forget deletes wa_user) removes them too.

-- One row per turn: the patches applied and the query_state version they produced (undo, debugging, benchmark).
CREATE TABLE query_patch_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_key    text NOT NULL REFERENCES wa_user ON DELETE CASCADE,
    version     integer NOT NULL,                    -- query_state.version after this turn
    patch       jsonb NOT NULL DEFAULT '[]',         -- the patch ops applied; [] = a turn that changed nothing
    message_id  text,                                -- WAMID of the turn's last inbound message
    turn_job_id bigint,                              -- the turn job that wrote it: a re-claimed job does not log twice
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_key, version)
);
CREATE UNIQUE INDEX query_patch_log_turn ON query_patch_log (turn_job_id) WHERE turn_job_id IS NOT NULL;

-- A ranked list shown to the farmer: resolves "2 number wali" (latest answer, 24 h) and quoted replies (reply_wamid).
CREATE TABLE answer_shown (
    answer_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_key    text NOT NULL REFERENCES wa_user ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('PRICE', 'F1', 'F2', 'F3')),
    run_id      text,                                -- forecast/outlook run the numbers came from; NULL for PRICE
    positions   jsonb NOT NULL,                      -- ["OKARA","LAHORE",…]: position n -> positions[n-1] (mandi id)
    reply_wamid text,                                -- WAMID of our reply; a quoted reply's context.id matches it
    shown_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX answer_shown_latest ON answer_shown (user_key, shown_at DESC, answer_id DESC);
CREATE INDEX answer_shown_quote ON answer_shown (reply_wamid) WHERE reply_wamid IS NOT NULL;

-- The one open question per farmer; no tool call that needs `slot` while it is open (file 06 §5.4).
CREATE TABLE pending_clarification (
    user_key    text PRIMARY KEY REFERENCES wa_user ON DELETE CASCADE,
    slot        text NOT NULL CHECK (slot IN ('crop', 'place', 'quantity_unit', 'horizon')),
    candidates  jsonb NOT NULL DEFAULT '[]',
    asked_wamid text,
    turns_open  integer NOT NULL DEFAULT 0,          -- ignored turns so far: 1 = re-asked once, 2 = expired (deleted)
    expires_at  timestamptz NOT NULL                 -- backstop: asked + 24 h (the service window)
);
