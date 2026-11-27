"""Task 7.2 DONE check (file 11): crop switch, place add, quantity correction, position reference, 24 h expiry; plus the
clarification lifecycle (file 06 §5.4) and the 30-day reset. Choices: DECISIONS.md D-032.

Patch values are built with the real resolver/normaliser (6.1, 5.4), so the state holds what the parser will produce.
The expected `state_after` for the crop switch is SPEC §2.4's M-FU-02 example, verbatim.
"""
import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app import state as st
from app.migrate import migrate
from mandi.normalise import quantity
from mandi.resolve import resolve_crop, resolve_place

NOW = datetime(2026, 12, 11, 9, 0, tzinfo=UTC)


def crop(raw, op="set"):
    return {"slot": "crop", "op": op, "raw": raw, "value": resolve_crop(raw).ids[0]}


def place(raw, op="set", role="ORIGIN"):
    r = resolve_place(raw)
    return {"slot": "place", "op": op, "raw": raw,
            "value": {"canonical": r.ids[0], "status": r.status, "role": role, "mandi_ids": list(r.mandi_ids)}}


def qty(raw, op="set"):
    q = quantity(raw)
    return {"slot": "quantity", "op": op, "raw": raw, "value": {"value": q.value, "unit": q.unit, "value_kg": q.value_kg}}


def intent(name):
    return {"slot": "intent", "op": "set", "raw": None, "value": name}


def okara_onion_50():
    """M-FU-02 context turn: "Okara se 50 mann pyaz kahan bechoon"."""
    return st.apply({}, [intent("WHERE_TO_SELL"), crop("pyaz"), place("Okara"), qty("50 mann")], "text", NOW)


def test_first_turn_snapshot_is_the_spec_context_state_after():
    assert st.snapshot(okara_onion_50()) == {"intent": "WHERE_TO_SELL", "crop": "ONION",
                                             "place": {"canonical": "OKARA", "role": "ORIGIN"},
                                             "quantity_kg": 2000, "horizon": None}


# --- DONE condition: crop switch, place add, quantity correction ------------------------------------------------------

def test_crop_switch_keeps_place_quantity_and_intent():
    s = st.apply(okara_onion_50(), [crop("tamatar")], "text", NOW + timedelta(minutes=1))
    assert st.snapshot(s) == {"intent": "WHERE_TO_SELL", "crop": "TOMATO",  # SPEC §2.4 M-FU-02 gold state_after
                              "place": {"canonical": "OKARA", "role": "ORIGIN"}, "quantity_kg": 2000, "horizon": None}
    assert s["crop"]["raw"] == "tamatar"


def test_place_add_is_a_union_of_mandis_and_keeps_the_origin():
    s = st.apply(okara_onion_50(), [place("Lahore", op="add")], "text", NOW)
    assert s["place"]["value"]["mandi_ids"] == ["OKARA", "LAHORE"]
    assert st.snapshot(s)["place"] == {"canonical": "OKARA", "role": "ORIGIN"}
    again = st.apply(s, [place("Lahore", op="add")], "text", NOW)  # adding it twice changes nothing
    assert again["place"]["value"]["mandi_ids"] == ["OKARA", "LAHORE"]


def test_place_add_with_no_place_yet_is_a_set():
    s = st.apply({}, [place("Lahore", op="add", role="MANDI")], "text", NOW)
    assert s["place"]["value"]["mandi_ids"] == ["LAHORE"]
    assert st.snapshot(s)["place"] == {"canonical": "LAHORE", "role": "MANDI"}


def test_quantity_correction_replaces_and_marks_the_old_value():
    s = st.apply(okara_onion_50(), [qty("80 mann", op="correct")], "text", NOW)
    assert s["quantity"]["value"] == {"value": 80, "unit": "MANN", "value_kg": 3200}
    assert st.snapshot(s)["quantity_kg"] == 3200
    assert s["quantity"]["corrected_from"] == {"value": {"value": 50, "unit": "MANN", "value_kg": 2000}, "raw": "50 mann"}
    assert st.snapshot(s)["crop"] == "ONION"  # nothing else moved


# --- other ops and provenance -----------------------------------------------------------------------------------------

def test_new_intent_replaces_the_old_one_and_clear_drops_a_slot():
    s = st.apply(okara_onion_50(), [intent("FORECAST"), {"slot": "quantity", "op": "clear"}], "text", NOW)
    assert st.snapshot(s)["intent"] == "FORECAST"
    assert "quantity" not in s and st.snapshot(s)["quantity_kg"] is None
    assert st.apply(s, [{"slot": "quantity", "op": "clear"}], "text", NOW) == s  # clearing an empty slot is fine


def test_horizon_set_is_the_gold_horizon_shape():
    s = st.apply(okara_onion_50(), [{"slot": "horizon", "op": "set", "raw": "agle hafte", "value": {"kind": "DAYS", "h": 7}}],
                 "text", NOW)
    assert st.snapshot(s)["horizon"] == {"kind": "DAYS", "h": 7}


def test_every_slot_carries_provenance():
    t = NOW + timedelta(hours=1)
    s = st.apply(okara_onion_50(), [{**crop("tamatar"), "confidence": 0.82}], "voice", t)
    assert s["crop"] == {"value": "TOMATO", "raw": "tamatar", "source": "voice", "confidence": 0.82, "confirmed": False,
                         "updated_at": t.isoformat()}
    assert s["place"]["source"] == "text" and s["place"]["updated_at"] == NOW.isoformat()  # untouched slot keeps its own
    pin = st.apply({}, [{**place("Okara"), "confirmed": True}], "pin", NOW)
    assert (pin["place"]["source"], pin["place"]["confirmed"]) == ("pin", True)


def test_no_patches_returns_the_same_state_and_apply_never_mutates_its_input():
    s = okara_onion_50()
    before = json.dumps(s, sort_keys=True)
    assert st.apply(s, [], "text", NOW + timedelta(days=1)) == s
    st.apply(s, [crop("tamatar"), place("Lahore", op="add"), qty("80 mann", op="correct")], "text", NOW)
    assert json.dumps(s, sort_keys=True) == before


def test_ref_is_not_a_state_change():
    s = okara_onion_50()
    assert st.apply(s, [{"op": "ref", "position": 2}], "text", NOW) == s


@pytest.mark.parametrize("patch", [{"slot": "crop", "op": "merge"}, {"slot": "colour", "op": "set"},
                                   {"slot": "crop", "op": "add", "value": "ONION"}])
def test_bad_patches_are_rejected(patch):
    with pytest.raises(ValueError):
        st.apply({}, [patch], "text", NOW)


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError):
        st.apply({}, [crop("pyaz")], "sms", NOW)


def test_state_is_plain_json():
    """Decimals from normalise.quantity become numbers, so the state can be stored as jsonb (Jsonb uses json.dumps)."""
    s = st.apply(okara_onion_50(), [qty("dedh mann", op="correct")], "text", NOW)
    assert json.loads(json.dumps(s)) == s
    assert s["quantity"]["value"] == {"value": 1.5, "unit": "MANN", "value_kg": 60}


# --- 30-day reset -----------------------------------------------------------------------------------------------------

def test_state_resets_after_30_days_idle():
    s = okara_onion_50()
    assert st.expire_if_idle(s, NOW, NOW + timedelta(days=30)) == s
    assert st.expire_if_idle(s, NOW, NOW + timedelta(days=30, seconds=1)) == {}


# --- DB: answer positions, clarification, jsonb round-trip ------------------------------------------------------------

@pytest.fixture
def conn(db):
    migrate(db)
    with psycopg.connect(db, autocommit=True) as c:
        for u in ("US.A", "US.B"):
            c.execute("INSERT INTO wa_user (user_key, consent_at) VALUES (%s, now())", (u,))
        yield c


def test_position_reference_uses_the_latest_answer(conn):
    st.record_answer(conn, "US.A", "F2", "run-1", ["SAHIWAL", "OKARA", "LAHORE"], "wamid.R1", NOW - timedelta(hours=2))
    st.record_answer(conn, "US.A", "F2", "run-2", ["LAHORE", "OKARA", "SAHIWAL"], "wamid.R2", NOW - timedelta(hours=1))
    st.record_answer(conn, "US.B", "F2", "run-3", ["MULTAN", "KASUR"], "wamid.R3", NOW)  # another farmer's is not used
    assert st.resolve_position(conn, "US.A", 2, NOW) == "OKARA"
    assert st.resolve_position(conn, "US.A", 1, NOW) == "LAHORE"
    assert st.resolve_position(conn, "US.A", 0, NOW) is None
    assert st.resolve_position(conn, "US.A", 4, NOW) is None
    assert st.resolve_position(conn, "US.B", 2, NOW) == "KASUR"


def test_position_reference_with_no_answer_is_none(conn):
    assert st.resolve_position(conn, "US.A", 1, NOW) is None


def test_positions_expire_after_24_hours(conn):
    st.record_answer(conn, "US.A", "F2", "run-1", ["LAHORE", "OKARA"], "wamid.R1", NOW - timedelta(hours=24))
    assert st.resolve_position(conn, "US.A", 2, NOW) == "OKARA"  # exactly 24 h: still valid
    assert st.resolve_position(conn, "US.A", 2, NOW + timedelta(seconds=1)) is None  # 24 h + 1 s


def test_quoted_reply_picks_that_answer_even_when_old(conn):
    st.record_answer(conn, "US.A", "F2", "run-1", ["SAHIWAL", "OKARA"], "wamid.OLD", NOW - timedelta(days=3))
    st.record_answer(conn, "US.A", "F1", "run-2", ["LAHORE"], "wamid.NEW", NOW - timedelta(days=2))
    assert st.resolve_position(conn, "US.A", 2, NOW, quoted_wamid="wamid.OLD") == "OKARA"  # file 06 §5.2
    assert st.resolve_position(conn, "US.A", 1, NOW) is None  # unquoted: latest is 2 days old
    assert st.resolve_position(conn, "US.B", 1, NOW, quoted_wamid="wamid.OLD") is None  # not this farmer's answer


def test_clarification_is_reasked_once_then_expires_after_2_turns(conn):
    st.open_clarification(conn, "US.A", "place", ["OKARA", "LAHORE"], "wamid.Q", NOW)
    assert st.pending(conn, "US.A", NOW) == {"slot": "place", "candidates": ["OKARA", "LAHORE"], "asked_wamid": "wamid.Q",
                                             "turns_open": 0}
    assert st.blocks(conn, "US.A", ["crop", "place"], NOW)  # no tool call that needs the place while it is open
    assert not st.blocks(conn, "US.A", ["crop"], NOW)
    assert st.tick(conn, "US.A", NOW) == "REASK"  # ignored once: kept, re-ask
    assert st.pending(conn, "US.A", NOW)["turns_open"] == 1
    assert st.tick(conn, "US.A", NOW) == "EXPIRED"  # ignored twice: gone
    assert st.pending(conn, "US.A", NOW) is None and not st.blocks(conn, "US.A", ["place"], NOW)
    assert st.tick(conn, "US.A", NOW) is None


def test_clarification_answered_closes_it(conn):
    st.open_clarification(conn, "US.A", "quantity_unit", [50, 100], None, NOW)
    assert not st.answer_clarification(conn, "US.A", [crop("pyaz")])  # a different slot does not answer it
    assert st.answer_clarification(conn, "US.A", [qty("50 kg")])
    assert st.pending(conn, "US.A", NOW) is None


def test_one_open_question_per_farmer_and_the_ttl_backstop(conn):
    st.open_clarification(conn, "US.A", "place", ["OKARA", "LAHORE"], "wamid.Q1", NOW)
    st.tick(conn, "US.A", NOW)
    st.open_clarification(conn, "US.A", "horizon", [], "wamid.Q2", NOW)  # replaces the first, counter restarts
    assert st.pending(conn, "US.A", NOW)["slot"] == "horizon" and st.pending(conn, "US.A", NOW)["turns_open"] == 0
    later = NOW + st.CLARIFY_TTL + timedelta(seconds=1)
    assert st.pending(conn, "US.A", later) is None
    assert st.tick(conn, "US.A", later) == "EXPIRED"


def test_state_round_trips_through_query_state(conn):
    s = st.apply(okara_onion_50(), [qty("dedh mann", op="correct"), place("Lahore", op="add")], "voice", NOW)
    conn.execute("INSERT INTO query_state (user_key, state) VALUES ('US.A', %s)", (Jsonb(s),))
    assert conn.execute("SELECT state FROM query_state WHERE user_key = 'US.A'").fetchone()[0] == s
