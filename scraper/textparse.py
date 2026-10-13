"""Plain-text parsers for battle infobox fields.

These functions work on text that has already been flattened from wikitext
(see ``infobox.flatten``), so they can be tested on any plain string.

- parse_year(date_text)          -> int | None   (negative = BC)
- parse_strength(strength_text)  -> float | None (personnel only)
- parse_result(result_text)      -> (kind, phrase) where kind is one of
                                    "victory", "defeat", "draw", "unknown"
- match_side(phrase, sides)      -> index of the side the phrase names, or None
"""
from __future__ import annotations

import math
import re
import statistics

# --------------------------------------------------------------------------- #
# Shared cleanup
# --------------------------------------------------------------------------- #
_CITE = re.compile(r"\[(?:\d+|[a-z]|note \w+|nb \d+|citation needed|clarification needed|"
                   r"dubious[^\]]*|according to whom\?|which\?|when\?|by whom\?|"
                   r"page needed|better source needed|failed verification)\]", re.I)
_WS = re.compile(r"[ \t   ]+")


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = _CITE.sub("", text)
    text = text.replace("−", "-")
    text = _WS.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


# --------------------------------------------------------------------------- #
# Year
# --------------------------------------------------------------------------- #
_MONTHS = ("january february march april may june july august september october "
           "november december jan feb mar apr jun jul aug sep sept oct nov dec spring "
           "summer autumn fall winter").split()
_YEAR_TOKEN = re.compile(
    r"(?P<pre>\b(?:AD|CE)\s*)?(?P<num>\d{1,4})(?P<s>s)?(?:\s*(?P<era>BCE|BC|B\.C\.|AD|CE|A\.D\.)\b)?",
    re.I)
_CENTURY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)\s+(?:century|c\.)\s*(BCE|BC)?", re.I)


def parse_year(text: str | None) -> int | None:
    """Best-guess year of a battle from its infobox date. BC years are negative."""
    text = clean(text)
    if not text:
        return None
    text = text.split("\n")[0] if re.search(r"\d", text.split("\n")[0]) else text
    # "218–201 BC": the era applies to both ends of the range
    text = re.sub(r"(\d{1,4})\s*(?:-|–|—|to)\s*(\d{1,4})\s*(BCE|BC)\b", r"\1 \3 – \2 \3", text)
    candidates: list[tuple[int, int]] = []  # (priority, year)
    for m in _YEAR_TOKEN.finditer(text):
        num = int(m.group("num"))
        era = (m.group("era") or "").upper().replace(".", "")
        pre = m.group("pre")
        after = text[m.end():m.end() + 12].lower().lstrip(" ,.")
        before = text[max(0, m.start() - 12):m.start()].lower()
        # skip day-of-month numbers ("18 June 1815", "June 18, 1815")
        if not era and not pre and num <= 31 and (
                any(after.startswith(mo) for mo in _MONTHS)
                or any(before.rstrip(" ,").endswith(mo) for mo in _MONTHS)):
            continue
        # skip ordinal/century numbers and durations
        if re.match(r"(st|nd|rd|th)\b", text[m.end():m.end() + 2], re.I):
            continue
        if re.match(r"\s*(days?|weeks?|months?|years?|hours?)\b", text[m.end():m.end() + 8], re.I):
            continue
        if era in ("BC", "BCE"):
            candidates.append((0, -num))
        elif era in ("AD", "CE") or pre:
            candidates.append((0, num))
        elif num >= 100:
            candidates.append((1, num))
        else:
            candidates.append((2, num))
    if candidates:
        best = min(c[0] for c in candidates)
        years = [y for p, y in candidates if p == best]
        # A BC date range like "218–201 BC" only tags the last number.
        if any(y < 0 for y in years):
            return min(years)
        return years[0]
    m = _CENTURY.search(text)
    if m:
        c = int(m.group(1))
        mid = (c - 1) * 100 + 50
        return -mid if m.group(2) else mid
    return None


# --------------------------------------------------------------------------- #
# Strength
# --------------------------------------------------------------------------- #
# Things that are counted in strength fields but are not people.
_NON_PERSONNEL = (
    r"ships?|ships? of the line|vessels?|galleys?|galleons?|frigates?|sloops?|brigs?|boats?|"
    r"men[- ]of[- ]war|man[- ]of[- ]war|warships?|junks?|longships?|triremes?|quinqueremes?|"
    r"destroyers?|cruisers?|battleships?|battlecruisers?|carriers?|submarines?|u-boats?|"
    r"corvettes?|gunboats?|monitors?|transports?|landing craft|"
    r"guns?|cannons?|cannon|artillery|artillery pieces|pieces|mortars?|howitzers?|"
    r"rocket launchers?|launchers?|machine guns?|"
    r"tanks?|armou?red|vehicles?|apcs?|ifvs?|cars?|trucks?|half-tracks?|"
    r"aircraft|planes?|airplanes?|fighters?|bombers?|helicopters?|drones?|uavs?|sorties?|"
    r"elephants?|camels?|horses?|oxen|mules?|chariots?|siege engines?|catapults?|trebuchets?|"
    r"technicals?|camp[- ]followers?|civilians?|non-combatants?|"
    r"divisions?|brigades?|regiments?|battalions?|companies|company|squadrons?|corps|armies|"
    r"army groups?|fleets?|flotillas?|wings?|groups?|cohorts?|tumens?|"
    r"km|miles?|kilometres?|kilometers?|hours?|days?|years?|%|percent")
_NON_PERSONNEL_RE = re.compile(r"^\s*(?:\+|\)|\]|\s|[a-z\-]+\s){0,3}?(?:" + _NON_PERSONNEL + r")\b", re.I)
_LEGION_RE = re.compile(r"^\s*(?:\+\s*)?(?:roman\s+)?legions?\b", re.I)
_PERSONNEL_UNITS = re.compile(
    r"^\s*(?:\+\s*)?(infantry|cavalry|horsemen|knights|archers|men-at-arms|men|soldiers|troops|"
    r"warriors|sailors|marines|militia|personnel|samurai|hoplites|peltasts|skirmishers|"
    r"auxiliaries|levies|crossbowmen|longbowmen|pikemen|musketeers|dragoons|hussars|"
    r"lancers|riflemen|paratroopers|commandos|fighters|regulars|irregulars|mercenaries|"
    r"volunteers|guerrillas|rebels|insurgents|police|officers|crew|crewmen)\b", re.I)
_NUM = r"\d{1,3}(?:[,.  ]\d{3})+|\d+(?:\.\d+)?"
_QTY = re.compile(
    r"(?<![\w.])(?P<a>" + _NUM + r")(?P<amult>\s*(?:million|thousand|k)\b)?"
    r"(?:\s*(?:-|–|—|to)\s*(?P<b>" + _NUM + r")(?P<bmult>\s*(?:million|thousand|k)\b)?)?"
    r"(?P<plus>\s*\+)?", re.I)
_MULT = {"million": 1_000_000, "thousand": 1_000, "k": 1_000}
_ALT_SOURCES = re.compile(r"\b(source|sources|estimate[sd]?|according|claimed?|est\.|range[sd]?|between|"
                          r"max\.?|maximum|min\.?|minimum|up to|at most|at least|reported(?:ly)?)\b|\bor\b", re.I)
_PHASES = re.compile(r"\b(initial(?:ly)?|final(?:ly)?|later|at (?:the )?peak|peak|maximum|"
                     r"minimum|reinforce\w*|rising|eventually|by the end|at the start)\b", re.I)
_TOTAL = re.compile(r"\btotal\b", re.I)


def _to_number(raw: str, mult: str | None) -> float:
    raw = raw.replace(" ", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", raw):
        val = float(re.sub(r"[,.]", "", raw))
    else:
        val = float(raw.replace(",", ""))
    if mult:
        val *= _MULT[mult.strip().lower()]
    return val


def _quantities(text: str):
    """Yield (value, line_no, unit_word, is_total) for personnel quantities."""
    for line_no, line in enumerate(text.split("\n")):
        is_total_line = bool(_TOTAL.search(line))
        for m in _QTY.finditer(line):
            a = _to_number(m.group("a"), m.group("amult"))
            val = a
            if m.group("b"):
                b = _to_number(m.group("b"), m.group("bmult") or m.group("amult"))
                # "20–25,000" style shorthand
                if a < 1000 <= b and a * 1000 <= b * 2 and m.group("b").count(",") + m.group("b").count(".") >= 1 \
                        and not m.group("amult"):
                    a *= 1000
                if b >= a:
                    val = (a + b) / 2
            rest = line[m.end():]
            # Year-ish numbers inside dates, e.g. "(1914)" — skip 4-digit values in parentheses
            if 1000 <= val <= 2100 and re.match(r"\s*\)", rest) and line[max(0, m.start() - 1):m.start()] == "(":
                continue
            if _LEGION_RE.match(rest):
                yield val * 5000, line_no, "legion", is_total_line
                continue
            if _NON_PERSONNEL_RE.match(rest):
                continue
            unit = _PERSONNEL_UNITS.match(rest)
            unit_word = unit.group(1).lower() if unit else ""
            before = line[max(0, m.start() - 12):m.start()]
            yield val, line_no, unit_word, is_total_line or bool(_TOTAL.search(before))


def parse_strength(text: str | None) -> float | None:
    """Estimate the number of personnel from an infobox strength field."""
    text = clean(text)
    text = re.sub(r"\d+\s*[⁄/]\s*\d+", " ", text)  # fractions like 5⁄6
    if not text:
        return None
    # Pull parenthesised breakdowns out of the main text, but fall back to
    # them if nothing is left outside the parentheses.
    outside = re.sub(r"\([^()]*\)", " ", text)
    qs = [q for q in _quantities(outside) if q[0] >= 1]
    if not qs:
        qs = [q for q in _quantities(text) if q[0] >= 1]
    if not qs:
        return None
    totals = [q[0] for q in qs if q[3]]
    if totals:
        return max(totals)
    # Drop stray tiny numbers ("Task Force 8") unless they are clearly people.
    biggest = max(q[0] for q in qs)
    qs = [q for q in qs if q[2] or (q[0] >= 20 and q[0] >= biggest / 100)] or qs
    vals = [q[0] for q in qs]
    if len(vals) == 1:
        return vals[0]
    biggest = max(vals)
    rest = sum(vals) - biggest
    if abs(biggest - rest) / biggest < 0.15:      # last number is the total
        return biggest
    if _ALT_SOURCES.search(text):                  # competing estimates
        return float(statistics.median(vals))
    if _PHASES.search(text):                       # "initially X, later Y"
        return biggest
    return float(sum(vals))                        # breakdown by unit / country


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #
_ADJ = set("""decisive major minor pyrrhic phyrric pyrhic tactical tactically strategic strategically
overwhelming crushing marginal narrow limited partial partially complete total initial ultimate
eventual final military political overall nominal qualified clear costly significant important
moral operational a an the""".split())
_DRAW = re.compile(r"\b(draw|drawn|stalemate|inconclusive|indecisive|undecided|status quo|"
                   r"ceasefire|cease-fire|truce|armistice|mutual withdrawal|both sides claim)", re.I)
_LOSS_WORDS = re.compile(r"^(.*?)\b(defeat|retreat|withdrawal|withdraws|withdrew|repulsed|routed|surrender)\b", re.I)


def _strip_adj(phrase: str) -> str:
    words = [w for w in re.split(r"\s+", phrase.strip(" ,;:-–—.()")) if w]
    while words and words[0].lower().strip(",") in _ADJ:
        words.pop(0)
    while words and words[-1].lower().strip(",") in _ADJ:
        words.pop()
    return " ".join(words).strip(" ,;:-–—.")


def parse_result(text: str | None) -> tuple[str, str]:
    """Classify an infobox result.

    Returns (kind, phrase): kind is "victory" (phrase names the winner),
    "defeat" (phrase names the loser), "draw", or "unknown".
    """
    text = clean(text)
    if not text:
        return "unknown", ""
    head = text.split("\n")[0]
    if re.fullmatch(r"(see|refer to)\b.*", head, re.I):
        return "unknown", ""
    clauses = [c.strip() for c in re.split(r"[;\n]|,\s*(?=(?:but|and)?\s*(?:tactical|strategic|decisive|major|pyrrhic|indecisive|inconclusive))|\.\s+", text) if c.strip()]
    if not clauses:
        return "unknown", ""
    # Prefer the tactical outcome (that is what WAR measures), then the first clause.
    tactical = [c for c in clauses if re.search(r"\btactic", c, re.I)]
    ordered = tactical + [c for c in clauses if c not in tactical]
    for clause in ordered[:3]:
        low = clause.lower()
        m = re.search(r"^(.*?)\bvictor(?:y|ies|ious)\b(.*)$", clause, re.I)
        if m:
            before, after = m.group(1), m.group(2)
            phrase = _strip_adj(before)
            if not phrase:
                m2 = re.match(r"\s*(?:for|of|to)\s+(?:the\s+)?(.+)", after, re.I)
                if m2:
                    phrase = _strip_adj(re.split(r"[,;(]| over | against ", m2.group(1))[0])
            if phrase and not _DRAW.search(phrase):
                return "victory", phrase
        if _DRAW.search(low):
            return "draw", ""
        m = re.search(r"^(.*?)\b(?:won|wins|win|prevail(?:s|ed)?|triumph)\b", clause, re.I)
        if m and _strip_adj(m.group(1)):
            return "victory", _strip_adj(m.group(1))
        m = _LOSS_WORDS.search(clause)
        if m and _strip_adj(m.group(1)):
            return "defeat", _strip_adj(m.group(1))
        if tactical and clause in tactical:
            continue
        break
    return "unknown", ""


# --------------------------------------------------------------------------- #
# Matching a result phrase ("French", "Union", "Anglo-Allied") to a side
# --------------------------------------------------------------------------- #
_STOP = set("""the of and kingdom empire republic state states forces force army armies navy
people peoples tribes tribe dynasty sultanate caliphate khanate principality duchy county
emirate imperial royal federal free first second third new holy great greater united with
supported support by from in on at for under led loyal rebels
government nation nations""".split())

# Irregular demonyms -> a word that appears in the polity's name.
DEMONYMS = {
    "french": "france", "english": "england", "british": "britain", "spanish": "spain",
    "dutch": "netherlands", "swedish": "sweden", "swedes": "sweden", "danish": "denmark",
    "danes": "denmark", "polish": "poland", "poles": "poland", "turkish": "turkey",
    "turks": "turkey", "greek": "greece", "greeks": "greece", "swiss": "switzerland",
    "scottish": "scotland", "scots": "scotland", "welsh": "wales", "irish": "ireland",
    "portuguese": "portugal", "hungarian": "hungary", "hungarians": "hungary",
    "russian": "russia", "russians": "russia", "prussian": "prussia", "prussians": "prussia",
    "austrian": "austria", "austrians": "austria", "german": "germany", "germans": "germany",
    "chinese": "china", "japanese": "japan", "american": "united", "americans": "united",
    "carthaginian": "carthage", "carthaginians": "carthage", "roman": "rome", "romans": "rome",
    "athenian": "athens", "athenians": "athens", "spartan": "sparta", "spartans": "sparta",
    "macedonian": "macedon", "macedonians": "macedon", "persian": "persia", "persians": "persia",
    "israeli": "israel", "egyptian": "egypt", "egyptians": "egypt", "soviet": "soviet",
    "venetian": "venice", "venetians": "venice", "genoese": "genoa", "norwegian": "norway",
    "finnish": "finland", "finns": "finland", "burgundian": "burgundy", "burgundians": "burgundy",
    "castilian": "castile", "aragonese": "aragon", "neapolitan": "naples", "savoyard": "savoy",
    "bavarian": "bavaria", "saxon": "saxony", "saxons": "saxony", "hessian": "hesse",
    "lithuanian": "lithuania", "serbian": "serbia", "serbs": "serbia", "bulgarian": "bulgaria",
    "bulgarians": "bulgaria", "romanian": "romania", "croatian": "croatia", "croats": "croatia",
    "bohemian": "bohemia", "indian": "india", "pakistani": "pakistan", "afghan": "afghanistan",
    "afghans": "afghanistan", "iranian": "iran", "iraqi": "iraq", "syrian": "syria",
    "jordanian": "jordan", "lebanese": "lebanon", "korean": "korea", "koreans": "korea",
    "vietnamese": "vietnam", "thai": "thailand", "burmese": "burma", "mexican": "mexico",
    "mexicans": "mexico", "peruvian": "peru", "chilean": "chile", "bolivian": "bolivia",
    "paraguayan": "paraguay", "argentine": "argentina", "argentinian": "argentina",
    "brazilian": "brazil", "colombian": "colombia", "venezuelan": "venezuela", "cuban": "cuba",
    "ethiopian": "ethiopia", "italian": "italy", "italians": "italy", "sicilian": "sicily",
    "siamese": "siam", "tibetan": "tibet", "texian": "texas", "texan": "texas",
    "ukrainian": "ukraine", "georgian": "georgia", "armenian": "armenia", "armenians": "armenia",
    "kurdish": "kurdistan", "libyan": "libya", "sudanese": "sudan", "somali": "somalia",
    "yemeni": "yemen", "saudi": "saudi", "filipino": "philippines", "philippine": "philippines",
    "indonesian": "indonesia", "malaysian": "malaysia", "mongol": "mongol", "mongols": "mongol",
    "mongolian": "mongol", "byzantine": "byzantine", "byzantines": "byzantine",
    "ottoman": "ottoman", "ottomans": "ottoman", "union": "union", "confederate": "confederate",
    "confederates": "confederate", "norman": "normandy", "normans": "normandy",
    "frankish": "francia", "franks": "francia", "visigothic": "visigoths", "ostrogothic": "ostrogoths",
    "anglo": "england", "habsburg": "habsburg", "hapsburg": "habsburg", "flemish": "flanders",
    "moroccan": "morocco", "algerian": "algeria", "tunisian": "tunisia", "zulus": "zulu",
    "boers": "boer", "seleucid": "seleucid", "ptolemaic": "ptolemaic", "parthian": "parthia",
    "parthians": "parthia", "sasanian": "sasanian", "sassanid": "sasanian", "umayyad": "umayyad",
    "abbasid": "abbasid", "fatimid": "fatimid", "ayyubid": "ayyubid", "mamluk": "mamluk",
    "mamluks": "mamluk", "timurid": "timurid", "safavid": "safavid", "mughal": "mughal",
    "mughals": "mughal", "maratha": "maratha", "marathas": "maratha", "sikh": "sikh",
    "sikhs": "sikh", "manchu": "qing", "jurchen": "jin", "khmer": "khmer", "aztec": "aztec",
    "aztecs": "aztec", "inca": "inca", "incan": "inca", "gaulish": "gaul", "gauls": "gaul",
    "celtic": "celts", "germanic": "germani", "goths": "goth", "gothic": "goth",
    "vandals": "vandal", "huns": "hun", "hunnic": "hun", "arab": "arab", "arabs": "arab",
    "muslim": "muslim", "muslims": "muslim", "rashidun": "rashidun", "crusader": "crusader",
    "crusaders": "crusader", "jacobite": "jacobite", "jacobites": "jacobite",
    "royalist": "royalist", "royalists": "royalist", "parliamentarian": "parliament",
    "parliamentarians": "parliament", "republican": "republican", "republicans": "republican",
    "nationalist": "nationalist", "nationalists": "nationalist", "communist": "communist",
    "communists": "communist", "patriot": "continental", "patriots": "continental",
    "loyalist": "loyalist", "loyalists": "loyalist", "sardinian": "sardinia",
    "piedmontese": "sardinia", "welfs": "welf", "guelph": "guelph", "ghibelline": "ghibelline",
    "hellenic": "greece", "kievan": "kiev", "muscovite": "moscow", "muscovy": "moscow",
    "novgorodian": "novgorod", "tatar": "tatar", "tatars": "tatar", "tartar": "tatar",
    "cossack": "cossack", "cossacks": "cossack", "polish-lithuanian": "poland",
    "anglo-allied": "england", "allied": "allies", "axis": "axis",
}


def _stem(word: str) -> str:
    return word


def tokens(text: str) -> set[str]:
    out: set[str] = set()
    for raw in re.findall(r"[A-Za-zÀ-ÿ'\-]+", text or ""):
        w = raw.lower().strip("'-")
        if not w:
            continue
        parts = [w] + (w.split("-") if "-" in w else [])
        for p in parts:
            if len(p) < 3 or p in _STOP:
                continue
            canon = DEMONYMS.get(p, p)
            out.add(_stem(canon))
    return out


def match_side(phrase: str, sides: list[set[str]], phrase_links: list[str] | None = None,
               side_links: list[set[str]] | None = None) -> int | None:
    """Return the index of the side named by ``phrase``.

    ``sides`` are token sets built with ``tokens()`` from each side's combatant
    text (including link targets and flag-template country names).
    """
    want = tokens(phrase)
    for link in phrase_links or []:
        want |= tokens(link)
    if not want:
        return None
    scores = []
    for i, side in enumerate(sides):
        s = sum(1 for w in want if any(_same(w, t) for t in side))
        if phrase_links and side_links:
            s += 3 * len(set(phrase_links) & side_links[i])
        scores.append(s)
    best = max(scores)
    if best == 0 or scores.count(best) > 1:
        return None
    return scores.index(best)


def _same(a: str, b: str) -> bool:
    """Same word, or one is a short extension of the other (Biafra/Biafran)."""
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return long_.startswith(short) and len(long_) - len(short) <= 2


def logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))
