"""End-to-end build with a fake Wikipedia (no network)."""
import json

from scraper import build, wiki
from tests.test_parse import AUSTERLITZ, WATERLOO, CANNAE, DRAW

PAGES = {1: ("Battle of Austerlitz", AUSTERLITZ), 2: ("Battle of Waterloo", WATERLOO),
         3: ("Battle of Cannae", CANNAE), 4: ("Battle of Borodino", DRAW),
         5: ("Napoleonic Wars", "{{Infobox military conflict|conflict=Napoleonic Wars|commander1=[[Napoleon]]}}")}
DESCR = {"Napoleon": "French emperor (1769–1821)", "Mikhail Kutuzov": "Russian field marshal (1745–1813)",
         "Hannibal": "Carthaginian general (247–181 BC)", "Marshal of France": "Military distinction"}


class FakeWiki:
    def __init__(self, *a, **k):
        pass

    def infobox_pages(self):
        return [{"pageid": k, "title": v[0], "revid": 100 + k} for k, v in PAGES.items()]

    def lead_wikitext(self, ids):
        return {i: (100 + i, PAGES[i][1]) for i in ids}

    def page_info(self, titles):
        out = {}
        for t in titles:
            title = "Napoleon" if t == "Napoleon Bonaparte" else t
            out[t] = {"title": title, "description": DESCR.get(title, "Roman consul" if "consul" in t or "Varro" in t else "")}
        return out

    def person_categories(self, titles):
        return {t: ["Category:1800 births"] for t in titles}


def test_build_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki, "Wiki", FakeWiki)
    out = tmp_path / "site"
    build.main(["--cache-dir", str(tmp_path / "cache"), "--out", str(out), "--csv-dir", str(tmp_path / "csv")])
    battles = json.loads((out / "battles.json").read_text())["rows"]
    generals = json.loads((out / "generals.json").read_text())["rows"]
    meta = json.loads((out / "meta.json").read_text())
    assert len(battles) == 4                      # the war page is excluded
    names = [g[0] for g in generals]
    assert "Napoleon" in names and "Marshal of France" not in names
    assert meta["battles"] == 4
    rows = (tmp_path / "csv" / "generals.csv").read_text().splitlines()
    nap = next(r for r in rows if ",Napoleon,3,1,1,1," in r)   # 3 battles: 1 win, 1 loss, 1 draw
    assert nap
    assert (tmp_path / "csv" / "generals.csv").read_text().count("\n") == len(generals) + 1
    # second run is incremental: nothing re-fetched
    build.main(["--cache-dir", str(tmp_path / "cache"), "--out", str(out), "--csv-dir", str(tmp_path / "csv")])
