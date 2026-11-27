"""Query state manager (task 7.2, RFC C7; file 06 §4–5; SPEC §2.4). Choices: DECISIONS.md D-032.

Pure part (no DB): `apply` merges op-based slot patches into the farmer's query state, keeping per-slot provenance;
`snapshot` gives the SPEC §2.4 `state_after` shape; `expire_if_idle` resets a state idle for over 30 days.
DB part: `record_answer` / `resolve_position` (answer positions: latest answer only, valid 24 h; a quoted reply may pick
an older one) and the pending-clarification lifecycle (one open question per farmer, re-ask once, expire after 2 turns).

State (stored as query_state.state jsonb, so only JSON values: ints/floats, never Decimal; ISO strings for times):
    {"intent":   {"value": "WHERE_TO_SELL", **provenance},
     "crop":     {"value": "ONION", ...},
     "place":    {"value": {"canonical": "OKARA", "status": "RESOLVED", "role": "ORIGIN", "mandi_ids": ["OKARA"]}, ...},
     "quantity": {"value": {"value": 50, "unit": "MANN", "value_kg": 2000}, ...},
     "horizon":  {"value": {"kind": "DAYS", "h": 3}, ...}}
    provenance = raw, source (text|voice|pin|inferred), confidence, confirmed, updated_at [, corrected_from]
Patch (SPEC §2.4 with `id` generalised to `value`): {"slot", "op", "raw", "value"[, "confidence", "confirmed"]}.
"""
import copy
from datetime import datetime, timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

SLOTS = ("intent", "crop", "place", "quantity", "horizon")
OPS = ("set", "add", "clear", "correct", "ref")  # ref = a list position: resolved by resolve_position, not a state change
SOURCES = ("text", "voice", "pin", "inferred")
IDLE_RESET = timedelta(days=30)   # file 06 §4: query_state resets after 30 days idle
POSITION_TTL = timedelta(hours=24)  # file 06 §4: positions valid for the latest answer only, for 24 h
CLARIFY_TTL = timedelta(hours=24)   # backstop next to the 2-turn rule (D-032): the service window
CLARIFY_MAX_IGNORED = 2             # file 06 §5.4: keep, re-ask once, expire after 2 turns


def _jsonable(v):
    """Decimal → int/float (normalise.quantity returns Decimals; Jsonb uses json.dumps), recursively."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    return v


def _check(p: dict, source: str) -> None:
    if p.get("op") not in OPS:
        raise ValueError(f"unknown patch op {p.get('op')!r}")
    if p["op"] == "ref":
        return
    if p.get("slot") not in SLOTS:
        raise ValueError(f"unknown slot {p.get('slot')!r}")
    if p["op"] == "add" and p["slot"] != "place":
        raise ValueError("op 'add' is only for place (file 06 §4.1 'Lahore ka bhi')")
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")


def _slot(p: dict, source: str, now: datetime) -> dict:
    return {
        "value": _jsonable(p.get("value")),
        "raw": p.get("raw"),
        "source": source,
        "confidence": float(p.get("confidence", 1.0)),
        "confirmed": bool(p.get("confirmed", False)),
        "updated_at": now.isoformat(),
    }


def apply(state: dict, patches: list[dict], source: str, now: datetime) -> dict:
    """Return the state after `patches` (input not modified). Ops (file 06 §4.1):
    set: replace the slot (a new intent replaces the old one; every other slot is kept, so "aur tamatar?" keeps place,
         quantity and intent); add (place only): union of mandi ids, canonical/role kept ("Lahore ka bhi"; with no place
         yet it is a set); clear: drop the slot; correct ("nahi, 80 mann"): set, and the slot keeps
         corrected_from = the old {value, raw}; ref: no state change. No patches → the same state, untouched."""
    new = copy.deepcopy(state)
    for p in patches:
        _check(p, source)
        op, slot = p["op"], p.get("slot")
        if op == "ref":
            continue
        if op == "clear":
            new.pop(slot, None)
        elif op == "add" and slot in new:
            old = new[slot]
            ids = list(old["value"]["mandi_ids"])
            ids += [m for m in _jsonable(p["value"]).get("mandi_ids", []) if m not in ids]
            new[slot] = {**_slot(p, source, now), "raw": old["raw"], "value": {**old["value"], "mandi_ids": ids}}
        else:  # set, correct, add to an empty place
            fresh = _slot(p, source, now)
            if op == "correct" and slot in new:
                fresh["corrected_from"] = {"value": new[slot]["value"], "raw": new[slot]["raw"]}
            new[slot] = fresh
    return new


def snapshot(state: dict) -> dict:
    """The SPEC §2.4 `state_after` shape, so 15.3 can score the multi-turn items directly."""
    def val(slot):
        return state[slot]["value"] if slot in state else None
    place, qty = val("place"), val("quantity")
    return {
        "intent": val("intent"),
        "crop": val("crop"),
        "place": {"canonical": place["canonical"], "role": place["role"]} if place else None,
        "quantity_kg": qty["value_kg"] if qty else None,
        "horizon": val("horizon"),
    }


def expire_if_idle(state: dict, updated_at: datetime, now: datetime) -> dict:
    """Whole state resets after 30 days idle (checked on load). Exactly 30 days is still kept."""
    return {} if now - updated_at > IDLE_RESET else state


# --- answer positions (DB) --------------------------------------------------------------------------------------------

def record_answer(conn, user_key: str, kind: str, run_id: str | None, positions: list[str], reply_wamid: str | None,
                  now: datetime) -> int:
    """Store a ranked list we just sent (RFC §3 step 9). positions[n-1] is the mandi id shown at position n."""
    return conn.execute(
        "INSERT INTO answer_shown (user_key, kind, run_id, positions, reply_wamid, shown_at)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING answer_id",
        (user_key, kind, run_id, Jsonb(list(positions)), reply_wamid, now),
    ).fetchone()[0]


def resolve_position(conn, user_key: str, n: int, now: datetime, quoted_wamid: str | None = None) -> str | None:
    """Position n → mandi id, or None (caller re-fetches or asks). Numbers are always re-fetched by the caller.
    Quoted reply (context.id = one of our reply WAMIDs): that answer, however old (file 06 §5.2).
    Otherwise ("2 number wali"): the farmer's latest answer only, and only if shown within the last 24 h (file 06 §4)."""
    row = None
    if quoted_wamid is not None:
        row = conn.execute(
            "SELECT positions, shown_at FROM answer_shown WHERE user_key = %s AND reply_wamid = %s", (user_key, quoted_wamid)
        ).fetchone()
        if row is not None:
            positions, _ = row
            return positions[n - 1] if 1 <= n <= len(positions) else None
    row = conn.execute(  # an unknown quote falls back to the latest-answer rule
        "SELECT positions, shown_at FROM answer_shown WHERE user_key = %s ORDER BY shown_at DESC, answer_id DESC LIMIT 1",
        (user_key,),
    ).fetchone()
    if row is None:
        return None
    positions, shown_at = row
    if now - shown_at > POSITION_TTL or not 1 <= n <= len(positions):
        return None
    return positions[n - 1]


# --- pending clarification (DB; file 06 §5.4) -------------------------------------------------------------------------

_CLARIFY_FILLED_BY = {"crop": "crop", "place": "place", "quantity_unit": "quantity", "horizon": "horizon"}


def open_clarification(conn, user_key: str, slot: str, candidates: list, asked_wamid: str | None, now: datetime) -> None:
    """Ask one question. One open question per farmer: a new one replaces the old one."""
    conn.execute(
        "INSERT INTO pending_clarification (user_key, slot, candidates, asked_wamid, turns_open, expires_at)"
        " VALUES (%s, %s, %s, %s, 0, %s) ON CONFLICT (user_key) DO UPDATE SET slot = EXCLUDED.slot,"
        " candidates = EXCLUDED.candidates, asked_wamid = EXCLUDED.asked_wamid, turns_open = 0, expires_at = EXCLUDED.expires_at",
        (user_key, slot, Jsonb(_jsonable(candidates)), asked_wamid, now + CLARIFY_TTL),
    )


def pending(conn, user_key: str, now: datetime) -> dict | None:
    """The open question, or None (an expired one counts as closed)."""
    row = conn.execute(
        "SELECT slot, candidates, asked_wamid, turns_open FROM pending_clarification WHERE user_key = %s AND expires_at >= %s",
        (user_key, now),
    ).fetchone()
    return dict(zip(("slot", "candidates", "asked_wamid", "turns_open"), row, strict=True)) if row else None


def answer_clarification(conn, user_key: str, patches: list[dict]) -> bool:
    """Close the open question if this turn's patches fill its slot (set/add/correct). True if it was answered."""
    row = conn.execute("SELECT slot FROM pending_clarification WHERE user_key = %s", (user_key,)).fetchone()
    if row is None:
        return False
    filled = {p.get("slot") for p in patches if p.get("op") in ("set", "add", "correct")}
    if _CLARIFY_FILLED_BY[row[0]] not in filled:
        return False
    conn.execute("DELETE FROM pending_clarification WHERE user_key = %s", (user_key,))
    return True


def tick(conn, user_key: str, now: datetime) -> str | None:
    """A turn that did not answer the open question: keep it and re-ask once ("REASK"); the second ignored turn, or one
    after expires_at, drops it ("EXPIRED"). None if no question is open. The caller still processes the new slots."""
    row = conn.execute(
        "SELECT turns_open, expires_at FROM pending_clarification WHERE user_key = %s", (user_key,)
    ).fetchone()
    if row is None:
        return None
    turns_open, expires_at = row
    if turns_open + 1 >= CLARIFY_MAX_IGNORED or now > expires_at:
        conn.execute("DELETE FROM pending_clarification WHERE user_key = %s", (user_key,))
        return "EXPIRED"
    conn.execute("UPDATE pending_clarification SET turns_open = turns_open + 1 WHERE user_key = %s", (user_key,))
    return "REASK"


def blocks(conn, user_key: str, required: list[str], now: datetime) -> bool:
    """The gate: True while an open question is on a slot the tool call needs (crop/place/quantity_unit/horizon)."""
    p = pending(conn, user_key, now)
    return p is not None and p["slot"] in required


# --- load / save (DB; called by handlers.handle_turn under the farmer's advisory lock) ---------------------------------

def load(conn, user_key: str, now: datetime) -> dict:
    """The farmer's state, creating the row on first use. Idle over 30 days → {} and the open question is dropped too
    (D-032); the reset is persisted by the turn's save, and the version keeps counting up."""
    conn.execute("INSERT INTO query_state (user_key) VALUES (%s) ON CONFLICT DO NOTHING", (user_key,))
    state, updated_at = conn.execute(
        "SELECT state, updated_at FROM query_state WHERE user_key = %s", (user_key,)
    ).fetchone()
    if now - updated_at > IDLE_RESET:
        conn.execute("DELETE FROM pending_clarification WHERE user_key = %s", (user_key,))
        return {}
    return state


def save(conn, user_key: str, state: dict, patches: list[dict], message_id: str | None, turn_job_id: int) -> int | None:
    """Write the state (version + 1) and its one query_patch_log row, in one transaction. Returns the new version, or None
    if this turn job already saved (a re-claimed job must not bump the version or log twice)."""
    with conn.transaction():
        if conn.execute("SELECT 1 FROM query_patch_log WHERE turn_job_id = %s", (turn_job_id,)).fetchone():
            return None
        version = conn.execute(
            "UPDATE query_state SET state = %s, version = version + 1, updated_at = now() WHERE user_key = %s"
            " RETURNING version",
            (Jsonb(state), user_key),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO query_patch_log (user_key, version, patch, message_id, turn_job_id) VALUES (%s, %s, %s, %s, %s)",
            (user_key, version, Jsonb(_jsonable(patches)), message_id, turn_job_id),
        )
    return version
