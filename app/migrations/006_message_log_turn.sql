-- Task 10.1 (RFC C11/C12; file 06 §4 message_log). Choices: DECISIONS.md D-047.
-- A text turn now writes one 'in' row (the farmer's text) and one 'out' row (our reply, keyed by the outbound WAMID).
-- intent / tool_calls_json: what the rule parser decided for the turn; validator_result: render.compose's result
-- ({"used": "template_only" | "llm", "attempts": [...]}), so a live check can prove no LLM-written number was sent.
-- tool_payload_json (the facts the template used) comes with 11.2.
ALTER TABLE message_log ADD COLUMN intent text;
ALTER TABLE message_log ADD COLUMN tool_calls_json jsonb;
ALTER TABLE message_log ADD COLUMN validator_result jsonb;
