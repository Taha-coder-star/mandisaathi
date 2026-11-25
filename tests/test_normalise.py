"""Task 5.4 DONE check: the normalisers over a table of cases, ≥ 80 at 100% (file 03 §5, benchmark SPEC §2.5).

Each row is one parametrized test. The date cases pin "now" to 2026-12-11 (the S-DEMO reference), so month horizons
match the benchmark gold. Pure functions: no DB, no network.
"""
from datetime import date
from decimal import Decimal

import pytest

from mandi import normalise as nz
from mandi.normalise import Quantity

D = Decimal
NOW = date(2026, 12, 11)  # SPEC §2.5: "the next such month after 2026-12-11"


# --- numbers ----------------------------------------------------------------------------------------------------------
NUMBERS = [
    # ASCII digits, grouping, decimals
    ("0", D(0)), ("5", D(5)), ("50", D(50)), ("3000", D(3000)), ("3,000", D(3000)), ("1,47,000", D(147000)),
    ("1.5", D("1.5")), ("0.25", D("0.25")),
    # Urdu / Arabic-Indic digits
    ("۵۰", D(50)), ("٣", D(3)), ("۱۰۰۰", D(1000)),
    # integer words
    ("ek", D(1)), ("do", D(2)), ("teen", D(3)), ("char", D(4)), ("chaar", D(4)), ("panch", D(5)), ("paanch", D(5)),
    ("che", D(6)), ("chhe", D(6)), ("saat", D(7)), ("aath", D(8)), ("nau", D(9)), ("das", D(10)), ("dus", D(10)),
    ("bees", D(20)), ("pachas", D(50)),
    # scales
    ("sau", D(100)), ("do sau", D(200)), ("teen sau", D(300)), ("hazaar", D(1000)), ("teen hazaar", D(3000)),
    ("lakh", D(100000)), ("do lakh", D(200000)),
    # fractions and modifiers
    ("dedh", D("1.5")), ("derh", D("1.5")), ("dhai", D("2.5")), ("dedh sau", D(150)), ("dhai sau", D(250)),
    ("dhai hazaar", D(2500)), ("sawa teen", D("3.25")), ("saade char", D("4.5")), ("paune do", D("1.75")),
    ("sawa sau", D(125)), ("saade sau", D(150)), ("paune sau", D(75)),
    # tens/teens and additive compounds (strictly falling scales)
    ("pachees", D(25)), ("chalees", D(40)), ("pandrah", D(15)), ("do sau pachaas", D(250)), ("ek sau do", D(102)),
    ("teen hazaar paanch sau", D(3500)), ("saadhe teen sau", D(350)), ("dedh lakh", D(150000)),
    ("do teen", None), ("sau hazaar", None), ("teen rate", None),
    # not a number
    ("foo", None), ("rate", None), ("", None), ("mann", None), ("pyaz ka", None),
]


@pytest.mark.parametrize("text,expected", NUMBERS)
def test_number(text, expected):
    got = nz.number(text)
    assert got == expected
    if expected is not None:
        assert str(got) == str(expected)  # clean repr: 150 not 150.0


# --- units ------------------------------------------------------------------------------------------------------------
UNITS = [
    ("mann", "MANN"), ("Maund", "MANN"), ("man", "MANN"), ("mn", "MANN"), ("من", "MANN"),
    ("kg", "KG"), ("KGS", "KG"), ("kilo", "KG"), ("kilogram", "KG"), ("کلو", "KG"),
    ("ton", "TON"), ("tonne", "TON"), ("ٹن", "TON"),
    ("bori", "BORI"), ("bag", "BORI"), ("بوری", "BORI"),
    ("crate", "CRATE"), ("peti", "CRATE"),
    ("xyz", None), ("pyaz", None), ("", None),
]


@pytest.mark.parametrize("text,expected", UNITS)
def test_unit(text, expected):
    assert nz.unit(text) == expected


# --- quantities -------------------------------------------------------------------------------------------------------
QUANTITIES = [
    ("50 mann", Quantity(D(50), "MANN", D(2000), False, None)),
    ("50mann", Quantity(D(50), "MANN", D(2000), False, None)),
    ("2 ton", Quantity(D(2), "TON", D(2000), False, None)),
    ("100 kg", Quantity(D(100), "KG", D(100), False, None)),
    ("1.5 mann", Quantity(D("1.5"), "MANN", D(60), False, None)),
    ("5 maund", Quantity(D(5), "MANN", D(200), False, None)),
    ("dedh sau mann", Quantity(D(150), "MANN", D(6000), False, None)),
    ("teen mann", Quantity(D(3), "MANN", D(120), False, None)),
    ("sawa teen mann", Quantity(D("3.25"), "MANN", D(130), False, None)),
    ("das kg", Quantity(D(10), "KG", D(10), False, None)),
    ("۵۰ mann", Quantity(D(50), "MANN", D(2000), False, None)),
    # bori / no-unit -> ask
    ("teen bori", Quantity(D(3), "BORI", None, True, "BAG_WEIGHT")),
    ("10 bori", Quantity(D(10), "BORI", None, True, "BAG_WEIGHT")),
    ("bori", Quantity(None, "BORI", None, True, "BAG_WEIGHT")),
    ("50", Quantity(D(50), "NONE", None, True, "NO_UNIT")),
    ("teen", Quantity(D(3), "NONE", None, True, "NO_UNIT")),
    # crate / peti -> always ask (file 03 §5)
    ("10 crate", Quantity(D(10), "CRATE", None, True, "CRATE_WEIGHT")),
    ("paanch peti", Quantity(D(5), "CRATE", None, True, "CRATE_WEIGHT")),
    # number words beyond one group; extra words before the number are ignored
    ("pachees mann", Quantity(D(25), "MANN", D(1000), False, None)),
    ("do sau pachaas mann", Quantity(D(250), "MANN", D(10000), False, None)),
    ("pyaz ka dedh sau mann", Quantity(D(150), "MANN", D(6000), False, None)),
    # unit only, no number
    ("mann", Quantity(None, "MANN", None, False, None)),
    # nothing quantity-like
    ("salaam", None), ("", None), ("pyaz", None),
]


@pytest.mark.parametrize("text,expected", QUANTITIES)
def test_quantity(text, expected):
    assert nz.quantity(text) == expected


def test_quantity_bori_with_crop_bag_weight_resolves():
    assert nz.quantity("10 bori", default_bag_kg=100) == Quantity(D(10), "BORI", D(1000), False, None)


def test_quantity_value_kg_matches_spec_factors():
    assert nz.quantity("3 mann").value_kg == 120   # ×40
    assert nz.quantity("3 kg").value_kg == 3        # ×1
    assert nz.quantity("3 ton").value_kg == 3000    # ×1000
    assert nz.quantity("3 bori").value_kg is None   # ask
    assert nz.quantity("3").value_kg is None        # ask


# --- horizons (PKT, now = 2026-12-11) ---------------------------------------------------------------------------------
TODAY = {"kind": "TODAY"}
AMB = {"kind": "AMBIGUOUS"}


def _days(h):
    return {"kind": "DAYS", "h": h}


def _month(m):
    return {"kind": "MONTH", "month": m}


HORIZONS = [
    ("aaj", None, TODAY), ("aj", None, TODAY), ("today", None, TODAY), ("آج", None, TODAY),
    ("kal ka rate", None, AMB), ("kal", None, AMB), ("کل", None, AMB),
    ("kal", True, _days(1)), ("کل", True, _days(1)),
    ("parson", None, AMB), ("parson", True, _days(2)),
    ("agle hafte", None, _days(7)), ("aglay hafte", None, _days(7)), ("next week", None, _days(7)),
    ("اگلے ہفتے", None, _days(7)),
    ("February mein", None, _month("2027-02")), ("feb", None, _month("2027-02")),
    ("april", None, _month("2027-04")), ("december", None, _month("2026-12")),
    ("january", None, _month("2027-01")), ("jan", None, _month("2027-01")), ("may", None, _month("2027-05")),
    ("مارچ", None, _month("2027-03")), ("جون", None, _month("2027-06")),
    ("next 3 days", None, _days(3)), ("agle 5 din mein", None, _days(5)), ("agle teen din", None, _days(3)),
    ("do din", None, _days(2)), ("tomorrow", None, _days(1)), ("day after tomorrow", None, _days(2)),
    ("kitne din", None, None),
    ("kuch bhi", None, None), ("", None, None), ("pyaz ka rate", None, None),
]


@pytest.mark.parametrize("text,future,expected", HORIZONS)
def test_horizon(text, future, expected):
    assert nz.horizon(text, NOW, future=future) == expected


def test_horizon_future_hint_only_affects_kal_and_parson():
    # a future verb does not turn a bare price query into a forecast
    assert nz.horizon("aaj", NOW, future=True) == TODAY
    assert nz.horizon("agle hafte", NOW, future=False) == _days(7)


def test_horizon_defaults_now_to_today_pkt():
    # with no `now`, a month resolves against the real PKT date; just check the shape and a valid month
    h = nz.horizon("january")
    assert h["kind"] == "MONTH" and h["month"].endswith("-01")
