"""Task 9.1: renderer + grounding validator. DONE check: an injected wrong number, a number word ("teen hazaar"), an
unknown mandi or "pakka" in the LLM framing is rejected; after one regeneration the template-only reply is sent."""
from datetime import date
from decimal import Decimal

import pytest

from app import render
from app.render import SYNTH, Reply, compose, per_mann, rs, validate
from mandi.price import Price


def price(stale=False, lo="7125", hi="7500", avg="7300", d=date(2026, 12, 11)):
    return Price(1, "ONION", "LAHORE", "SYN", None, d, *(Decimal(v) if v else None for v in (lo, hi, avg)),
                 age=3 if stale else 1, stale=stale)


FACTS = render.price(price(), "ru")
F1 = {"crop_id": "TOMATO", "mandi_id": "LAHORE", "h": 3, "p10": Decimal(5250), "p50": Decimal(5875), "p90": Decimal(6500),
      "reasons": ["ARRIVALS_HIGH", "NOT_A_CODE"]}
F2 = {"crop_id": "ONION", "origin_id": "OKARA", "quantity_mann": 50, "nearest_id": "OKARA", "transport_per_mann": 85, "km": 130,
      "commission_pct": 6, "run_id": "R-20261211",
      "rows": [{"mandi_id": "LAHORE", "p10": 7625, "p90": 8125, "net": 147000, "gain_vs_nearest": 2500},
               {"mandi_id": "OKARA", "p10": 7125, "p90": 7500, "net": 144500, "gain_vs_nearest": 0},
               {"mandi_id": "SAHIWAL", "p10": 7250, "p90": 7750, "net": 143800, "gain_vs_nearest": -700}]}


def scripted(*answers):
    calls = []

    def framing(reasons):
        calls.append(reasons)
        return answers[len(calls) - 1]
    return framing, calls


def test_scenario_1_line():
    assert FACTS.text == "Pyaz · Lahore · Rs 2,850–3,000 fi mann (40 kg) · 11 Dec · Demo data (synthetic)"
    assert [b["title"] for b in FACTS.buttons] == ["Agle din ka andaza", "Kahan bechoon?", "Alert lagayein"]
    assert "aakhri rate 11 Dec ka hai" in render.price(price(stale=True), "ru").text
    assert "Rs 2,920 fi mann" in render.price(price(lo="", hi=""), "ru").text  # avg only


@pytest.mark.parametrize("bad, reason", [
    ("Ji, Lahore mein pyaz Rs 3,100 ka hai.", "DIGIT"),            # injected wrong number
    ("Ji, Lahore mein pyaz teen hazaar ka hai.", "NUMBER_WORD:teen"),  # number word
    ("Ji, ye Multan ka taaza rate hai.", "UNKNOWN_PLACE:multan"),  # a mandi the tool did not return
    ("Ji, ye rate pakka hai.", "PROMISE:pakka"),                   # promise word
])
def test_done_rejected_twice_then_template_only_is_sent(bad, reason):
    framing, calls = scripted(bad, bad)
    reply, result = compose(FACTS, framing, {"LAHORE"})
    assert reply == FACTS  # byte for byte what send_text/send_buttons gets
    assert result["used"] == "template_only" and len(result["attempts"]) == 2
    assert reason in result["attempts"][0]["reasons"] and calls[1] == result["attempts"][0]["reasons"]


def test_clean_framing_is_kept_and_regeneration_can_fix_it():
    reply, result = compose(FACTS, scripted("Ji, ye Lahore ka taaza rate hai:")[0], {"LAHORE"})
    assert reply.text == "Ji, ye Lahore ka taaza rate hai:\n" + FACTS.text and reply.buttons == FACTS.buttons
    assert result == {"used": "llm", "attempts": [{"text": "Ji, ye Lahore ka taaza rate hai:", "reasons": []}]}
    reply, result = compose(FACTS, scripted("Rate 2850 hai", "Ji, ye taaza rate hai:")[0], {"LAHORE"})
    assert reply.text.startswith("Ji, ye taaza rate hai:\n") and result["attempts"][0]["reasons"] == ["DIGIT"]


def test_llm_failure_or_silence_never_loses_the_reply():
    def boom(_):
        raise TimeoutError
    assert compose(FACTS, boom) == (FACTS, {"used": "template_only", "attempts": [{"error": "TimeoutError"}]})
    assert compose(FACTS, None)[0] == FACTS
    assert compose(FACTS, lambda _: "  ")[0] == FACTS


@pytest.mark.parametrize("text", ["Rate ۳۰۰۰ hai", "It is three thousand rupees", "ریٹ تین ہزار ہے", "do sau mann",
                                  "Guarantee hai munafa hoga", "Karachi behtar hai", "line one\nline two", "x" * 201])
def test_more_rejections(text):
    assert validate(text, {"LAHORE"})


@pytest.mark.parametrize("text, allowed", [
    ("Is ki zaroorat ho to bata dein.", set()),  # 'zaroorat' (need) is not 'zaroor'
    ("Okara se Lahore behtar rahe ga.", {"OKARA", "LAHORE"}),  # the F2 origin is allowed too
    ("جی، یہ لاہور کا تازہ ریٹ ہے", {"LAHORE"}),
])
def test_ordinary_framing_passes(text, allowed):
    assert validate(text, allowed) == []


def test_number_format_and_per_mann():
    assert [rs(n) for n in (100, 2850, 147000, 12345678, -700)] == ["100", "2,850", "1,47,000", "1,23,45,678", "-700"]
    assert per_mann(Decimal("7126.25")) == 2851 and per_mann(7125) == 2850


def every_template(lang):
    yield render.price(price(stale=True), lang)
    yield render.price(None, lang, "ONION", "LAHORE")
    yield render.forecast(F1, lang)
    yield render.forecast({**F1, "h": 1, "reasons": []}, lang)
    yield render.no_forecast(price(), lang, "ONION", "LAHORE")
    yield render.where_to_sell(F2, lang)
    yield render.where_to_sell({**F2, "rows": [F2["rows"][1], F2["rows"][2]]}, lang)  # nearest on top
    for slot in ("crop", "place", "quantity", "quantity_unit", "horizon"):
        yield render.clarify(slot, lang)
    yield render.clarify("place", lang, ["DGKHAN", "RYKHAN"])
    yield render.clarify("place", lang, unknown_place=True)
    yield render.out_of_coverage(lang)
    yield render.out_of_scope(lang)
    yield render.unknown(lang)
    yield render.help_text(lang)
    yield render.join([render.price(price(), lang), render.price(None, lang, "POTATO", "LAHORE")])


@pytest.mark.parametrize("text, lang", [
    ("aloo ka rate", "ru"), ("pyaz", "ru"), ("Okara se pyaz kahan bechun", "ru"), ("help chahiye", "ru"),
    ("potato price in Sahiwal", "en"), ("help", "en"), ("where should I sell", "en"),
    ("آلو کا ریٹ", "ur"), ("Lahore آلو", "ur"),
])
def test_pick_lang(text, lang):
    assert render.pick_lang(text) == lang


def test_join_keeps_blocks_in_order_one_demo_line_first_buttons():
    a, b = render.price(price(), "ru"), render.price(None, "ru", "POTATO", "LAHORE")
    j = render.join([a, b])
    assert j.text.count(SYNTH) == 1 and j.text.index("Pyaz") < j.text.index("Aloo") and j.buttons == a.buttons


@pytest.mark.parametrize("lang", render.LANGS)
def test_every_template_fits_whatsapp_and_says_demo_data(lang):
    for r in every_template(lang):
        assert isinstance(r, Reply) and SYNTH in r.text, r
        assert len(r.text) <= (render.MAX_BODY if r.buttons else render.MAX_TEXT)
        assert len(r.buttons) <= 3 and all(0 < len(b["title"]) <= 20 for b in r.buttons), r.buttons


def test_template_contents():
    f1 = render.forecast(F1, "ru").text
    assert "agle 3 din ka andaza" in f1 and "Rs 2,100–2,600 fi mann (80% andaza)" in f1 and "Rs 2,350" in f1
    assert "Wajah: mandi mein aamad zyada hai\n" in f1 and "waada nahi" in f1
    f2 = render.where_to_sell(F2, "ru").text
    assert f2.startswith("Pyaz · 50 mann · Okara se\n1. Lahore: Rs 3,050–3,250 fi mann · kharche ke baad ≈ Rs 1,47,000")
    assert "Lahore nazdeeki mandi se ≈ Rs 2,500 zyada deti hai" in f2 and "transport Rs 85/mann (130 km), commission 6%" in f2
    near = render.where_to_sell({**F2, "rows": F2["rows"][1:]}, "ru").text
    assert "Nazdeeki mandi (Okara) theek hai" in near
    assert render.out_of_coverage("ru").text.startswith("Abhi sirf Punjab ki mandiyan aur pyaz, tamatar aur aloo.")
    # an unknown place says so (file 03 §4.3, V30/T-AMB-03); a missing place only asks (V29)
    assert render.clarify("place", "ru", unknown_place=True).text.startswith("Is jagah ki maloomat mere paas nahi.")
    assert "maloomat" not in render.clarify("place", "ru").text
    assert render.no_forecast(None, "ru", "ONION", "LAHORE").text.startswith("Is mandi ka andaza dene ke liye data kaafi nahi")
    assert "لاہور" in render.price(price(), "ur").text and "11 دسمبر" in render.price(price(), "ur").text
    assert SYNTH in render.CONSENT_TEXT and "STOP" in render.CONSENT_TEXT and "pakka" not in render.CONSENT_TEXT
