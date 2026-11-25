"""Crop + place gazetteer v0 (task 4.3; file 03 §3.2/§4, DECISIONS.md D-019).

  python -m mandi.gazetteer   (needs DATABASE_URL)

gazetteer.yaml -> crop, crop_alias, mandi, place, place_alias. Aliases are stored as norm(alias).
"""
import os
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import psycopg
import yaml

GAZETTEER = Path(__file__).with_name("gazetteer.yaml")
COLS = {  # insert order: aliases after the rows they point to
    "crop": ("crop_id", "name_en", "name_ur", "perishability_class", "default_unit", "default_bag_kg", "covered"),
    "crop_alias": ("alias_norm", "crop_id", "kind"),
    "mandi": ("mandi_id", "name_en", "name_ur", "city", "district", "province", "lat", "lon", "covered"),  # source_ids untouched
    "place": ("place_id", "name_en", "name_ur", "kind", "district", "province", "lat", "lon", "candidate_mandi_ids"),
    "place_alias": ("alias_norm", "place_id"),
}
# Arabic letter forms -> the Urdu ones; harakat, superscript alef and tatweel dropped
_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ه": "ہ", "ـ": None, "ٰ": None} | dict.fromkeys(range(0x064B, 0x0653)))


def norm(s: str) -> str:
    """NFKC, casefold, Urdu letter folding; punctuation/symbols/spaces/format chars -> one space. 'D.G. Khan' -> 'd g khan'."""
    s = unicodedata.normalize("NFKC", s).casefold().translate(_FOLD)
    return " ".join("".join(" " if unicodedata.category(ch)[0] in "PSZC" else ch for ch in s).split())


def read(path: Path = GAZETTEER) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def rows(gaz: dict) -> dict[str, list[tuple]]:
    """Table rows per COLS. Raises ValueError for an empty alias, an unplanned alias collision or an unknown target."""
    out: dict[str, list[tuple]] = {t: [] for t in COLS}
    names: dict[str, dict[tuple[str, str], str | None]] = {"crop": {}, "place": {}}  # (alias_norm, id) -> crop_alias.kind

    def add(table: str, alias: str, target: str, kind: str | None = None) -> None:
        if not (a := norm(alias)):
            raise ValueError(f"{table} alias {alias!r} of {target} is empty after normalisation")
        names[table].setdefault((a, target), kind)  # first kind wins (name_en/name_ur repeated in a list)

    for cid, c in gaz["crops"].items():
        out["crop"].append((cid, c["name_en"], c["name_ur"], c["perishability"], c["default_unit"], c.get("default_bag_kg"),
                            c["covered"]))
        add("crop", c["name_en"], cid, "OFFICIAL")
        add("crop", c["name_ur"], cid, "URDU_SCRIPT")
        for kind, aliases in c.get("aliases", {}).items():
            for a in aliases:
                add("crop", a, cid, kind)
    mandi_ids = {m["id"] for m in gaz["mandis"]}
    for m in gaz["mandis"]:
        out["mandi"].append((m["id"], m["name_en"], m["name_ur"], m["name_en"], m["district"], "Punjab", m["lat"], m["lon"], True))
    places = [(m, "Punjab", [m["id"]]) for m in gaz["mandis"]]
    places += [(p, p["province"], p.get("candidate_mandi_ids", [])) for p in gaz.get("other_places", [])]
    for p, province, candidates in places:
        if unknown := set(candidates) - mandi_ids:
            raise ValueError(f"place {p['id']}: candidates {sorted(unknown)} are not mandis")
        out["place"].append((p["id"], p["name_en"], p["name_ur"], p.get("kind", "CITY"), p["district"], province, p["lat"], p["lon"],
                             candidates))
        for a in (p["name_en"], p["name_ur"], *(a for group in p.get("aliases", {}).values() for a in group)):
            add("place", a, p["id"])

    targets = {"crop": set(gaz["crops"]), "place": {p["id"] for p, _, _ in places}}
    planned: dict[str, set[str]] = {"crop": set(), "place": set()}
    for table, aliases in gaz.get("ambiguous", {}).items():
        for alias, ids in aliases.items():
            if unknown := set(ids) - targets[table]:
                raise ValueError(f"ambiguous {table} alias {alias!r}: unknown targets {sorted(unknown)}")
            planned[table].add(norm(alias))
            for i in ids:
                add(table, alias, i, "COMMON")
    for table, found in names.items():
        if clash := {a for a, n in Counter(a for a, _ in found).items() if n > 1} - planned[table]:
            raise ValueError(f"{table} aliases name more than one target but are not under ambiguous: {sorted(clash)}")
    out["crop_alias"] = [(a, cid, kind) for (a, cid), kind in names["crop"].items()]
    out["place_alias"] = list(names["place"])
    return out


def load_gazetteer(conn: psycopg.Connection, gaz: dict | None = None) -> dict[str, int]:
    """Reload in one transaction: aliases replaced, crop/mandi/place upserted. Returns rows written per table.
    shortcut: rows removed from the YAML are not deleted (FKs from price_obs/forecast); delete by hand if ever needed."""
    data = rows(read() if gaz is None else gaz)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM crop_alias")
        cur.execute("DELETE FROM place_alias")
        for table, cols in COLS.items():
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
            if not table.endswith("_alias"):
                sql += f" ON CONFLICT ({cols[0]}) DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:])
            cur.executemany(sql, data[table])
    return {t: len(r) for t, r in data.items()}


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("gazetteer: DATABASE_URL is not set", file=sys.stderr)
        return 1
    with psycopg.connect(url, autocommit=True) as conn:  # autocommit: conn.transaction() is a real commit
        counts = load_gazetteer(conn)
    print("gazetteer: loaded " + ", ".join(f"{t} {n}" for t, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
