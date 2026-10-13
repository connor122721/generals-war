"""Minimal, polite client for the English Wikipedia Action API."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Iterable, Iterator

import requests

API = "https://en.wikipedia.org/w/api.php"
log = logging.getLogger("wiki")

DEFAULT_UA = ("GeneralsWAR/1.0 (+https://github.com/{repo}; Wikipedia battle-infobox research scraper) "
              "python-requests/{rv}")


def chunks(seq: list, n: int) -> Iterator[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class Wiki:
    def __init__(self, user_agent: str | None = None, delay: float = 0.1):
        repo = os.environ.get("GITHUB_REPOSITORY", "your-name/generals-war")
        self.s = requests.Session()
        self.s.headers["User-Agent"] = user_agent or DEFAULT_UA.format(repo=repo, rv=requests.__version__)
        self.s.headers["Accept-Encoding"] = "gzip"
        self.delay = delay
        self.calls = 0

    # ------------------------------------------------------------------ core
    def _get(self, params: dict) -> dict:
        params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        for attempt in range(8):
            try:
                r = self.s.get(API, params=params, timeout=60)
                self.calls += 1
                if r.status_code in (429, 500, 502, 503, 504):
                    wait = float(r.headers.get("Retry-After", 2 ** attempt))
                    log.warning("HTTP %s, sleeping %.0fs", r.status_code, wait)
                    time.sleep(min(wait, 120))
                    continue
                r.raise_for_status()
                data = r.json()
            except (requests.ConnectionError, requests.Timeout, ValueError) as e:
                log.warning("request failed (%s), retrying", e)
                time.sleep(2 ** attempt)
                continue
            err = data.get("error")
            if err and err.get("code") == "maxlag":
                time.sleep(float(r.headers.get("Retry-After", 5)))
                continue
            if err:
                raise RuntimeError(f"API error {err.get('code')}: {err.get('info')}")
            time.sleep(self.delay)
            return data
        raise RuntimeError("Wikipedia API kept failing; giving up")

    def query(self, params: dict) -> Iterator[dict]:
        """Run a query, following 'continue' until exhausted. Yields each response."""
        params = {"action": "query", **params}
        cont: dict = {}
        while True:
            data = self._get({**params, **cont})
            yield data
            if "continue" not in data:
                break
            cont = data["continue"]

    # ------------------------------------------------------------ battles
    def infobox_pages(self, template: str = "Template:Infobox military conflict") -> list[dict]:
        """Every article that transcludes the battle infobox, with its latest revision id."""
        pages = {}
        for data in self.query({"generator": "embeddedin", "geititle": template, "geinamespace": "0",
                                "geilimit": "max", "prop": "info"}):
            for p in data.get("query", {}).get("pages", []):
                pages[p["pageid"]] = {"pageid": p["pageid"], "title": p["title"], "revid": p.get("lastrevid")}
            log.info("listed %d pages", len(pages))
        return list(pages.values())

    def lead_wikitext(self, pageids: list[int]) -> dict[int, tuple[int, str]]:
        """Section-0 wikitext (where the infobox lives) for up to 50 pages."""
        out: dict[int, tuple[int, str]] = {}
        params = {"prop": "revisions", "rvprop": "ids|content", "rvslots": "main",
                  "pageids": "|".join(map(str, pageids)), "rvsection": "0"}
        try:
            responses = list(self.query(params))
        except RuntimeError as e:
            if "section" not in str(e).lower():
                raise
            params.pop("rvsection")
            responses = list(self.query(params))
        for data in responses:
            for p in data.get("query", {}).get("pages", []):
                revs = p.get("revisions")
                if revs:
                    rev = revs[0]
                    content = rev.get("slots", {}).get("main", {}).get("content", "")
                    out[p["pageid"]] = (rev.get("revid"), content)
        return out

    # ------------------------------------------------------------- people
    def page_info(self, titles: list[str]) -> dict[str, dict]:
        """Resolve redirects and fetch short description, thumbnail and categories hints.

        Returns {input_title: {"title", "description", "thumb", "disambig", "missing"}}.
        """
        out: dict[str, dict] = {}
        for batch in chunks(titles, 50):
            redirect: dict[str, str] = {}
            pages: dict[str, dict] = {}
            for data in self.query({"titles": "|".join(batch), "redirects": "1",
                                    "prop": "description|pageimages|pageprops",
                                    "piprop": "thumbnail", "pithumbsize": "120", "pilimit": "50",
                                    "ppprop": "disambiguation"}):
                q = data.get("query", {})
                for n in q.get("normalized", []):
                    redirect[n["from"]] = n["to"]
                for rd in q.get("redirects", []):
                    redirect[rd["from"]] = rd["to"]
                for p in q.get("pages", []):
                    cur = pages.setdefault(p["title"], {"title": p["title"]})
                    if p.get("missing") or p.get("invalid"):
                        cur["missing"] = True
                    if "description" in p:
                        cur["description"] = p["description"]
                    if "thumbnail" in p:
                        cur["thumb"] = p["thumbnail"]["source"]
                    if "disambiguation" in p.get("pageprops", {}):
                        cur["disambig"] = True
            for t in batch:
                final = t
                for _ in range(3):
                    final = redirect.get(final, final)
                out[t] = pages.get(final, {"title": final, "missing": True})
        return out

    def person_categories(self, titles: list[str]) -> dict[str, list[str]]:
        """Birth/death categories, used to recognise people with no short description."""
        out: dict[str, list[str]] = {t: [] for t in titles}
        for batch in chunks(titles, 50):
            for data in self.query({"titles": "|".join(batch), "prop": "categories",
                                    "cllimit": "max", "clshow": "!hidden"}):
                for p in data.get("query", {}).get("pages", []):
                    cats = [c["title"] for c in p.get("categories", [])]
                    out.setdefault(p["title"], []).extend(
                        c for c in cats if re.search(r"(births|deaths|Living people|Year of (birth|death))", c))
        return out


_LIFESPAN = re.compile(
    r"\(\s*(?:c\.|ca\.|circa|fl\.|r\.|born|died|b\.|d\.)?\s*(?:c\.\s*)?\d{1,4}(?:\s*(?:BC|BCE|AD|CE))?"
    r"(?:\s*(?:–|-|—|/)\s*(?:c\.\s*)?\d{1,4}(?:\s*(?:BC|BCE|AD|CE))?)?\s*\)|\b(?:born|died) (?:c\. )?\d{1,4}", re.I)
_PERSON_WORDS = re.compile(
    r"\b(general|admiral|commander|officer|soldier|marshal|field marshal|colonel|captain|major|lieutenant|"
    r"brigadier|sergeant|corporal|commodore|warlord|chieftain|chief|king|queen|emperor|empress|sultan|"
    r"sultana|shah|khan|khagan|caliph|emir|amir|pharaoh|tsar|czar|prince|princess|duke|duchess|earl|"
    r"count|countess|baron|lord|knight|noble|nobleman|aristocrat|monarch|ruler|regent|consul|dictator|"
    r"tribune|legate|satrap|governor|viceroy|statesman|politician|president|prime minister|minister|"
    r"revolutionary|rebel|guerrilla|militant|insurgent|pasha|bey|vizier|daimyo|samurai|shogun|"
    r"mercenary|condottiero|crusader|pirate|privateer|buccaneer|bishop|archbishop|pope|cardinal|"
    r"leader|aviator|pilot|explorer|conquistador|adventurer|nationalist|activist|terrorist|"
    r"person|man|woman|figure|hero|heroine|patriot|loyalist|philosopher|historian|writer|poet|"
    r"(?:ancient|medieval) [a-z]+ (?:general|ruler))\b", re.I)
_NOT_PERSON = re.compile(
    r"\b(disambiguation|army|navy|division|regiment|brigade|battalion|corps|fleet|squadron|unit|"
    r"formation|military branch|country|state in|city|town|village|empire|kingdom|dynasty|"
    r"organization|organisation|political party|militia group|armed forces|war|battle|siege|"
    r"family|clan|tribe|people|ethnic group|title|rank|ship|vessel|aircraft)\b", re.I)


_STRONG_PERSON = re.compile(r"\b(general|admiral|commander|officer|soldier|marshal|king|queen|emperor|"
                            r"empress|sultan|khan|ruler|leader|politician|statesman|prince|duke|warlord|"
                            r"chieftain|pharaoh|tsar|consul|noble|nobleman)\b", re.I)


def looks_like_person(description: str | None) -> bool | None:
    """True/False from a short description, or None when it can't tell
    (the caller then checks the page's birth/death categories)."""
    if not description:
        return None
    if re.search(r"\b(disambiguation|title|rank|honorific|award|decoration|order of)\b", description, re.I) \
            and not _LIFESPAN.search(description):
        return False
    person, lifespan_, not_person = (_PERSON_WORDS.search(description), _LIFESPAN.search(description),
                                     _NOT_PERSON.search(description))
    if not_person:
        if _STRONG_PERSON.search(description):
            return True
        return None if lifespan_ else False
    if person or lifespan_:
        return True
    return False


def lifespan(description: str | None) -> str:
    if not description:
        return ""
    m = _LIFESPAN.search(description)
    return m.group(0).strip("() ") if m else ""
