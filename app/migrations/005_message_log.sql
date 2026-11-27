-- Task 8.1 (RFC C4; file 06 §4 message_log; file 10 scenario 5 "message_log shows no STT call"). Choices: DECISIONS.md D-035.
-- 8.1 writes one row per inbound voice note: its transcript (NULL when there is none) and stt_meta (pre-check verdict,
-- duration, energy, every STT attempt). A re-claimed turn reuses the row instead of downloading and transcribing again.
-- Text rows and the intent / tool_calls_json / tool_payload_json / validator_result columns come with 9.1 / 11.2.
-- References wa_user ON DELETE CASCADE, so STOP (handlers._forget deletes wa_user) removes it too.
CREATE TABLE message_log (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_key           text NOT NULL REFERENCES wa_user ON DELETE CASCADE,
    wamid              text NOT NULL UNIQUE,
    direction          text NOT NULL CHECK (direction IN ('in', 'out')),
    modality           text NOT NULL CHECK (modality IN ('text', 'voice')),
    text_or_transcript text,
    stt_meta           jsonb,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX message_log_user ON message_log (user_key);
