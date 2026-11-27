"""FS-S short-term features for F1 (task 6.3; file 04 §1.2-1.3, DECISIONS.md D-029). Pure numpy, no DB, nothing fitted.

Timing rules enforced here (tests L1-L4 in tests/test_features.py):
  T1  a row is known on issue day t only if reported_at < t 00:00 PKT, i.e. from date_pkt(reported_at) + 1 day.
      LAST = the newest mid known at t (market date t-1 if it was published on time, else older).
  T2  every rolling, cross-mandi and seasonal statistic uses only rows known at t (windows end at t-1).
  T3  rain_features: forecast as issued before t, observed rain up to t-1 (no weather in the FYP-I synthetic data).
  T4-T5 nothing is fitted here: crop/mandi codes come from the fixed gazetteer order; scalers, encoders and conformal
      scores belong inside a model's fit(), which the harness calls on training rows only (L5).

Rows in: dicts shaped like price_obs (crop_id, mandi_id, market_date: date, reported_at: aware datetime,
min/max/avg_pkr100kg canonical PKR/100 kg, arrivals_qty, optional outlier_flag). Rows that are not OK are skipped.
"""
import math
import warnings
from datetime import date, datetime, time, timedelta, timezone

import numpy as np

from mandi.gazetteer import read
from mandi.resolve import _km

PKT = timezone(timedelta(hours=5), "PKT")  # Pakistan has no DST (same as the loader)
WINDOW = 28  # longest trailing window, days
NORM_YEARS, NORM_HALF = 3, 14  # arrivals norm: same +-14 days in each of the last 3 years
EVENT_CAP = 60  # days_to_event is capped here
PERISH = {"LOW": 0, "MED": 1, "HIGH": 2}
FEATURES = ["last", "age", "ret1", "ret7", "dev7", "dev28", "vol28", "spread_region", "spread_near3", "arrivals_dev",
            "weekday", "doy", "days_to_event", "crop", "mandi", "perish"]  # column 0 = harness LAST (PKR/100 kg)
XY_COLUMNS = [*FEATURES, "h"]
SAME_WEEKDAY = ["same_weekday", "same_weekday_lag"]  # B-SN input (task 7.3, D-033); not in the default X
NEVER = 1 << 40  # known-from index of an empty cell


def known_from(reported_at: datetime) -> date:
    """First issue day on which the row may be used (T1). reported_at must be timezone-aware."""
    if reported_at.tzinfo is None:
        raise ValueError("reported_at must be timezone-aware")
    return reported_at.astimezone(PKT).date() + timedelta(1)


def _mid(r: dict) -> float | None:
    """File 04 §1.2: M = (min + max) / 2; avg only when min or max is missing (10x typos hit avg, not min/max)."""
    lo, hi = r.get("min_pkr100kg"), r.get("max_pkr100kg")
    if lo is not None and hi is not None:
        return (float(lo) + float(hi)) / 2
    return None if r.get("avg_pkr100kg") is None else float(r["avg_pkr100kg"])


def spec_events(spec: dict) -> list[date]:
    """Ramadan start + both Eids per year from the synthetic spec's moving holidays (same rule as the generator).

    shortcut: Ramadan start = Eid ul Fitr - 30 days on a synthetic lunar calendar; FYP-II passes a real calendar instead.
    """
    p = spec["period"]
    mv = p["holidays"]["moving"]
    out = []
    for y in range(p["start"].year - 1, p["end"].year + 2):
        for b in mv["blocks"]:
            if b["name"] in ("eid_ul_fitr", "eid_ul_adha"):
                first = date(y, b["anchor"].month, b["anchor"].day) + timedelta(mv["drift_days_per_year"] * (y - mv["anchor_year"]))
                out.append(first)
                if b["name"] == "eid_ul_fitr":
                    out.append(first - timedelta(30))
    return sorted(out)


def _panel(rows):
    """Dense grids per series (crop, mandi) x calendar day: log mid P, log arrivals A, known-from day index K.

    shortcut: series = crop x mandi (file 04: x grade) and one source; two rows for one series-day raise. FYP-II graded
    exports must add grade to the key or filter to one grade; callers filter on source (SYN and SYN-NULL would collide).
    """
    obs = []
    for r in rows:
        if r.get("outlier_flag", "OK") != "OK" or (m := _mid(r)) is None or m <= 0:
            continue
        a = r.get("arrivals_qty")
        obs.append((r["crop_id"], r["mandi_id"], r["market_date"], known_from(r["reported_at"]), m,
                    float(a) if a is not None and float(a) > 0 else math.nan))
    if not obs:
        raise ValueError("no usable rows")
    d0 = min(o[2] for o in obs)
    keys = sorted({(o[0], o[1]) for o in obs})
    si = {k: i for i, k in enumerate(keys)}
    n = (max(max(o[2] for o in obs), max(o[3] for o in obs)) - d0).days + 1
    P, A = np.full((len(keys), n), np.nan), np.full((len(keys), n), np.nan)
    K = np.full((len(keys), n), NEVER, dtype=np.int64)
    for c, mid, d, kf, m, a in obs:
        s, i = si[(c, mid)], (d - d0).days
        if K[s, i] != NEVER:
            raise ValueError(f"two rows for {c}/{mid} on {d}")
        P[s, i], A[s, i], K[s, i] = math.log(m), math.log(a), (kf - d0).days
    return keys, d0, P, A, K


def _asof(V, K, s, t, offsets):
    """V[s, t - off] where that cell is known at t (K <= t), else NaN. t: (T,), offsets: (W,) -> (T, W)."""
    idx = t[:, None] - offsets[None, :]
    ok = idx >= 0
    idx = np.where(ok, idx, 0)
    return np.where(ok & (K[s, idx] <= t[:, None]), V[s, idx], np.nan)


def _newest(w):
    """F[:, k] = newest non-NaN value of w[:, k:] (w is newest-first); also the 1-based age of F[:, 0]."""
    F = w.copy()
    for k in range(w.shape[1] - 2, -1, -1):
        F[:, k] = np.where(np.isnan(w[:, k]), F[:, k + 1], w[:, k])
    has = ~np.isnan(w)
    age = np.where(has.any(axis=1), has.argmax(axis=1) + 1, np.nan)
    return F, age


def _features(keys, d0, P, A, K, t, events, gaz):
    """(S, T, len(FEATURES)) for issue-day indices t; every value uses only cells with K <= t."""
    lags = np.arange(1, WINDOW + 1)
    seasonal = np.array([365 * y + j for y in range(1, NORM_YEARS + 1) for j in range(-NORM_HALF, NORM_HALF + 1)])
    out = np.full((len(keys), len(t), len(FEATURES)), np.nan)
    col = {f: i for i, f in enumerate(FEATURES)}
    crop_code = {c: i for i, c in enumerate(gaz["crops"])}
    mandis = {m["id"]: m for m in gaz["mandis"]}
    mandi_code = {m: i for i, m in enumerate(mandis)}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows give NaN, which is the intended "unknown"
        for s, (crop, mandi) in enumerate(keys):
            w = _asof(P, K, s, t, lags)
            F, age = _newest(w)
            last = F[:, 0]
            arr = _newest(_asof(A, K, s, t, lags))[0][:, 0]
            o = out[s]
            o[:, col["last"]] = np.exp(last)
            o[:, col["age"]] = age
            o[:, col["ret1"]] = last - F[:, 1]
            o[:, col["ret7"]] = last - F[:, 7]
            o[:, col["dev7"]] = last - np.nanmean(w[:, :7], axis=1)
            o[:, col["dev28"]] = last - np.nanmean(w, axis=1)
            o[:, col["vol28"]] = np.nanstd(w, axis=1)
            o[:, col["arrivals_dev"]] = arr - np.nanmean(_asof(A, K, s, t, seasonal), axis=1)
            o[:, col["crop"]] = crop_code[crop]
            o[:, col["mandi"]] = mandi_code[mandi]
            o[:, col["perish"]] = PERISH[gaz["crops"][crop]["perishability"]]
        last = np.log(out[:, :, col["last"]])
        si = {k: i for i, k in enumerate(keys)}
        for s, (crop, mandi) in enumerate(keys):
            same = [i for i, k in enumerate(keys) if k[0] == crop]
            out[s, :, col["spread_region"]] = last[s] - np.nanmedian(last[same], axis=0)
            here = mandis[mandi]
            near = sorted((_km(here["lat"], here["lon"], m["lat"], m["lon"]), mid) for mid, m in mandis.items() if mid != mandi)
            nb = [si[(crop, mid)] for _, mid in near[:3] if (crop, mid) in si]  # 3 nearest gazetteer mandis: fixed, not fitted
            out[s, :, col["spread_near3"]] = last[s] - np.nanmean(last[nb], axis=0) if nb else np.nan
    days = np.datetime64(d0) + t.astype("timedelta64[D]")
    cap = days[-1] + np.timedelta64(EVENT_CAP, "D")  # sentinel: no next event -> capped
    ev = np.sort(np.append(np.array(events, dtype="datetime64[D]"), cap))
    to_event = (ev[np.searchsorted(ev, days)] - days).astype(float)
    dow = (days.astype("datetime64[D]").view("int64") - 4) % 7  # 1970-01-01 was a Thursday; 0 = Monday
    doy = (days - days.astype("datetime64[Y]")).astype(int) + 1
    out[:, :, col["weekday"]] = dow
    out[:, :, col["doy"]] = doy
    out[:, :, col["days_to_event"]] = np.minimum(to_event, EVENT_CAP)
    return out


def feature_table(rows, events=(), last_day: date | None = None, gaz: dict | None = None):
    """(keys, issue_days, F): F[s, i] = FS-S features of series keys[s] on issue day issue_days[i].

    Issue days run from the first market date + 1 through last_day (default: the last day any row becomes known).
    """
    keys, d0, P, A, K = _panel(rows)
    end = (last_day - d0).days if last_day else int(K[K != NEVER].max())
    if end >= P.shape[1]:
        pad = end + 1 - P.shape[1]
        P, A = (np.pad(V, ((0, 0), (0, pad)), constant_values=np.nan) for V in (P, A))
        K = np.pad(K, ((0, 0), (0, pad)), constant_values=NEVER)
    t = np.arange(1, end + 1)
    return keys, np.datetime64(d0) + t.astype("timedelta64[D]"), _features(keys, d0, P, A, K, t, events, gaz or read())


def xy_columns(same_weekday: bool = False) -> list[str]:
    """Column names of make_xy's X; the opt-in B-SN inputs sit just before h, so h stays X[:, -1]."""
    return [*FEATURES, *SAME_WEEKDAY, "h"] if same_weekday else XY_COLUMNS



def _same_weekday(P, K, t, h):
    """(S, T, 2): newest mid known at t on market date t+h-8 (same weekday as the target, one week earlier) or, if that
    cell is missing / not yet known, on the newest earlier day within WINDOW; plus its lag in days (8-h = exact).
    NaN when nothing qualifies (the B-SN baseline then falls back to LAST). Only cells with K <= t are read (T1)."""
    k = 7 - h  # w[:, k] holds lag k + 1 = 8 - h
    out = np.full((P.shape[0], len(t), 2), np.nan)
    for s in range(P.shape[0]):
        w = _asof(P, K, s, t, np.arange(1, WINDOW + 1))[:, k:]
        has = ~np.isnan(w)
        first = has.argmax(axis=1)
        any_ = has.any(axis=1)
        out[s, any_, 0] = np.exp(w[any_, first[any_]])
        out[s, any_, 1] = first[any_] + k + 1
    return out


def make_xy(rows, horizons=range(1, 8), events=(), gaz: dict | None = None, same_weekday: bool = False):
    """Harness rows (mandi.models.harness convention): X = XY_COLUMNS (col 0 = LAST), y = mid on market date t+h-1,
    dates = issue day t. Rows without a known LAST or without a target quote are dropped; other NaN features stay
    (LightGBM takes NaN; filter them for learners that don't). Pooled across horizons: filter by X[:, -1] == h.
    same_weekday=True adds the B-SN columns SAME_WEEKDAY before h (h <= 7 only); the default X is unchanged.
    """
    if same_weekday and max(horizons) > 7:
        raise ValueError("same_weekday needs h <= 7 (the same weekday last week must lie before the issue day)")
    keys, d0, P, A, K = _panel(rows)
    t = np.arange(1, P.shape[1])
    F = _features(keys, d0, P, A, K, t, events, gaz or read())
    days = np.datetime64(d0) + t.astype("timedelta64[D]")
    X, Y, D = [], [], []
    for h in horizons:
        tgt = t + h - 1
        ok = tgt < P.shape[1]
        y = np.full((len(keys), len(t)), np.nan)
        y[:, ok] = np.exp(P[:, tgt[ok]])
        keep = ~np.isnan(y) & ~np.isnan(F[:, :, 0])
        extra = [_same_weekday(P, K, t, h)[keep]] if same_weekday else []
        X.append(np.column_stack([F[keep], *extra, np.full(keep.sum(), h)]))
        Y.append(y[keep])
        D.append(np.broadcast_to(days, keep.shape)[keep])
    return np.concatenate(X), np.concatenate(Y), np.concatenate(D)


def rain_features(weather, t: date, h: int) -> tuple[float, float]:
    """T3 (L4): (observed rain mm over t-7..t-1, forecast rain mm for t..t+h-1 from the newest forecast issued before
    t 00:00 PKT). Realised weather on or after t is never used. weather: dicts like weather_daily rows for one district.

    shortcut: not wired into make_xy; FYP-I synthetic data has no weather (D-029). Wire it when weather_daily is filled.
    """
    cut = datetime.combine(t, time(0), PKT)
    seen = sum(float(w["rain_mm"]) for w in weather if not w["is_forecast"] and t - timedelta(7) <= w["date"] < t)
    issued = [w["issued_at"] for w in weather if w["is_forecast"] and w["issued_at"] < cut]
    if not issued:
        return seen, math.nan
    latest = max(issued)
    fc = sum(float(w["rain_mm"]) for w in weather
             if w["is_forecast"] and w["issued_at"] == latest and t <= w["date"] < t + timedelta(h))
    return seen, fc
