"""Scrape Wikipedia battle infoboxes and build the rankings.

    python -m scraper.build                 # full run (incremental if a cache exists)
    python -m scraper.build --limit 300     # quick test on the first 300 battle pages
    python -m scraper.build --offline       # rebuild from cache only, no network

Outputs
    site/data/{battles,generals,meta}.json  data for the interactive browser
    data/battles.csv, data/generals.csv     tidy tables for your own analysis
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import logging
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path

from . import infobox, model, wiki

log = logging.getLogger("build")
ROOT = Path(__file__).resolve().parents[1]
KIND_CODES = {"battle": 0, "siege": 1, "naval": 2, "operation": 3, "campaign": 4}
PEOPLE_TTL_DAYS = 30
THUMB_PREFIX = "https://upload.wikimedia.org/wikipedia/"


# ----------------------------------------------------------------- cache io
def load_gz(path: Path) -> dict:
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_gz(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


# ------------------------------------------------------------------ scrape
def fetch_battles(w: wiki.Wiki, cache_path: Path, limit: int | None, offline: bool) -> list[tuple[str, str]]:
    cache = load_gz(cache_path)  # {pageid: {"title", "revid", "box"}}
    if offline:
        pages = [{"pageid": int(k), "title": v["title"], "revid": v["revid"]} for k, v in cache.items()]
    else:
        pages = w.infobox_pages()
    pages.sort(key=lambda p: p["title"])
    if limit:
        pages = pages[:limit]
    todo = [p for p in pages if cache.get(str(p["pageid"]), {}).get("revid") != p["revid"]]
    log.info("%d pages with a battle infobox; %d new or changed since last run", len(pages), len(todo))
    t0 = time.time()
    for i, batch in enumerate(wiki.chunks(todo, 50)):
        got = w.lead_wikitext([p["pageid"] for p in batch])
        for p in batch:
            revid, text = got.get(p["pageid"], (p["revid"], ""))
            box = infobox.find_infobox(text) if text else None
            cache[str(p["pageid"])] = {"title": p["title"], "revid": revid, "box": str(box) if box else ""}
        if i % 20 == 0:
            log.info("fetched %d/%d (%.0fs)", min((i + 1) * 50, len(todo)), len(todo), time.time() - t0)
        if i % 200 == 199:
            save_gz(cache_path, cache)
    if todo:
        save_gz(cache_path, cache)
    keep = {str(p["pageid"]) for p in pages}
    return [(v["title"], v["box"]) for k, v in cache.items() if k in keep and v.get("box")]


def fetch_people(w: wiki.Wiki, titles: list[str], cache_path: Path, offline: bool) -> dict[str, dict]:
    cache = load_gz(cache_path)  # {link title: info}
    now = time.time()
    stale = [t for t in titles
             if t not in cache or now - cache[t].get("fetched", 0) > PEOPLE_TTL_DAYS * 86400]
    if offline:
        stale = []
    log.info("%d linked commander pages; %d to look up", len(titles), len(stale))
    for i, batch in enumerate(wiki.chunks(stale, 500)):
        info = w.page_info(batch)
        ambiguous = []
        for t in batch:
            d = info.get(t, {"title": t, "missing": True})
            d["fetched"] = now
            if d.get("missing") or d.get("disambig"):
                d["person"] = False
            else:
                d["person"] = wiki.looks_like_person(d.get("description"))
                if d["person"] is None:
                    ambiguous.append(d["title"])
            cache[t] = d
        if ambiguous:
            cats = w.person_categories(sorted(set(ambiguous)))
            for t in batch:
                if cache[t].get("person") is None:
                    cache[t]["person"] = bool(cats.get(cache[t]["title"]))
        log.info("people: %d/%d", min((i + 1) * 500, len(stale)), len(stale))
        if i % 10 == 9:
            save_gz(cache_path, cache)
    if stale:
        save_gz(cache_path, cache)
    return cache


# ------------------------------------------------------------------- build
def build(args) -> None:
    w = wiki.Wiki(delay=args.delay)
    cache_dir = Path(args.cache_dir)
    raw = fetch_battles(w, cache_dir / "battles.json.gz", args.limit, args.offline)

    battles = []
    for title, box in raw:
        try:
            b = infobox.parse_battle(title, box)
        except Exception as e:  # never let one odd page kill the run
            log.warning("could not parse %s: %s", title, e)
            continue
        if not b or b["kind"] == "war":
            continue
        battles.append(b)
    log.info("parsed %d battles (wars excluded)", len(battles))

    link_titles = sorted({l for b in battles for s in b["sides"] for l in s["commander_links"]})
    people = fetch_people(w, link_titles, cache_dir / "people.json.gz", args.offline)

    # canonical person title for each link
    canon = {t: people[t]["title"] for t in link_titles if t in people and people[t].get("person")}

    usable = []
    for b in battles:
        if len(b["sides"]) != 2 or b["winner"] is None:
            continue
        sides = []
        for s in b["sides"]:
            names = []
            for l in s["commander_links"]:
                c = canon.get(l)
                if c and c not in names:
                    names.append(c)
            sides.append(names)
        both = set(sides[0]) & set(sides[1])  # the same person on both sides = data error
        sides = [[n for n in sd if n not in both] for sd in sides]
        if not sides[0] and not sides[1]:
            continue
        usable.append({"title": b["title"], "year": b["year"], "kind": b["kind"],
                       "result": b["result"].split("\n")[0][:120], "winner": b["winner"],
                       "s1": b["sides"][0]["strength"], "s2": b["sides"][1]["strength"],
                       "c1": sides[0], "c2": sides[1]})
    log.info("%d battles have a known outcome and at least one linked commander", len(usable))

    fitres = model.fit(usable)
    coef = fitres["b"]
    log.info("strength model: b=%.3f (se %.3f) from %d battles", coef, fitres["se"] or 0, fitres["n"])
    for b in usable:
        b["p1"] = model.replacement_p1(b, coef)
        b["o1"] = model.outcome_side1(b["winner"])

    write_outputs(usable, people, fitres, args)


def write_outputs(usable: list[dict], people: dict, fitres: dict, args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    usable.sort(key=lambda b: (b["year"] if b["year"] is not None else 99999, b["title"]))

    # general index
    info_by_title: dict[str, dict] = {}
    for d in people.values():
        if d.get("person"):
            info_by_title.setdefault(d["title"], d)
    gid: dict[str, int] = {}
    for b in usable:
        for n in b["c1"] + b["c2"]:
            gid.setdefault(n, len(gid))

    generals_rows = []
    for name, i in sorted(gid.items(), key=lambda kv: kv[1]):
        d = info_by_title.get(name, {})
        thumb = d.get("thumb", "")
        generals_rows.append([name, d.get("description", ""),
                              thumb[len(THUMB_PREFIX):] if thumb.startswith(THUMB_PREFIX) else thumb,
                              wiki.lifespan(d.get("description"))])

    battle_rows = []
    for b in usable:
        battle_rows.append([b["title"], b["year"], KIND_CODES.get(b["kind"], 0), b["o1"], round(b["p1"], 3),
                            int(b["s1"]) if b["s1"] else None, int(b["s2"]) if b["s2"] else None,
                            [gid[n] for n in b["c1"]], [gid[n] for n in b["c2"]], b["result"]])

    # career summary (also used for CSV and meta)
    agg = defaultdict(lambda: {"n": 0, "w": 0, "l": 0, "d": 0, "war": 0.0, "shared": 0.0, "years": []})
    for b in usable:
        for side, names in ((0, b["c1"]), (1, b["c2"])):
            o = b["o1"] if side == 0 else 1 - b["o1"]
            p = b["p1"] if side == 0 else 1 - b["p1"]
            for n in names:
                a = agg[n]
                a["n"] += 1
                a["w" if o == 1 else "l" if o == 0 else "d"] += 1
                a["war"] += o - p
                a["shared"] += (o - p) / len(names)
                if b["year"] is not None:
                    a["years"].append(b["year"])
    ranked = sorted(agg.items(), key=lambda kv: -kv[1]["war"])

    meta = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": args.source_label,
        "battles": len(usable),
        "generals": len(gid),
        "with_strengths": sum(1 for b in usable if b["s1"] and b["s2"]),
        "model": {"b": round(fitres["b"], 4), "se": round(fitres["se"] or 0, 4), "n": fitres["n"],
                  "calibration": fitres["calibration"]},
        "kinds": list(KIND_CODES),
        "top": [{"name": n, "war": round(a["war"], 2)} for n, a in ranked[:10]],
    }
    dump = dict(ensure_ascii=False, separators=(",", ":"))
    (out / "battles.json").write_text(json.dumps({"rows": battle_rows}, **dump), encoding="utf-8")
    (out / "generals.json").write_text(json.dumps({"rows": generals_rows}, **dump), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    csv_dir = Path(args.csv_dir)
    csv_dir.mkdir(parents=True, exist_ok=True)
    with open(csv_dir / "battles.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["battle", "year", "kind", "result", "outcome_side1", "strength1", "strength2",
                     "p_replacement_side1", "commanders1", "commanders2", "url"])
        for b in usable:
            wr.writerow([b["title"], b["year"], b["kind"], b["result"], b["o1"], b["s1"] or "", b["s2"] or "",
                         round(b["p1"], 4), "; ".join(b["c1"]), "; ".join(b["c2"]),
                         "https://en.wikipedia.org/wiki/" + b["title"].replace(" ", "_")])
    with open(csv_dir / "generals.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["rank", "general", "battles", "wins", "losses", "draws", "war", "war_per_battle",
                     "war_shared", "first_year", "last_year", "median_year", "description", "url"])
        for rank, (n, a) in enumerate(ranked, 1):
            ys = a["years"]
            wr.writerow([rank, n, a["n"], a["w"], a["l"], a["d"], round(a["war"], 4), round(a["war"] / a["n"], 4),
                         round(a["shared"], 4), min(ys) if ys else "", max(ys) if ys else "",
                         int(statistics.median(ys)) if ys else "", info_by_title.get(n, {}).get("description", ""),
                         "https://en.wikipedia.org/wiki/" + n.replace(" ", "_")])
    log.info("wrote %d battles and %d generals to %s; top 5: %s", len(usable), len(gid), out,
             ", ".join(f"{t['name']} ({t['war']})" for t in meta["top"][:5]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default=str(ROOT / "data" / "cache"))
    ap.add_argument("--out", default=str(ROOT / "site" / "data"))
    ap.add_argument("--csv-dir", default=str(ROOT / "data"))
    ap.add_argument("--limit", type=int, help="only process the first N battle pages (for testing)")
    ap.add_argument("--offline", action="store_true", help="use cached pages only")
    ap.add_argument("--delay", type=float, default=0.1, help="seconds between API calls")
    ap.add_argument("--source-label", default="English Wikipedia battle infoboxes")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    build(args)


if __name__ == "__main__":
    main()
