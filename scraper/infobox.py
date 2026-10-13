"""Turn the wikitext of a battle article into a structured record."""
from __future__ import annotations

import html
import re

import mwparserfromhell as mwp
from mwparserfromhell.nodes import Comment, Tag, Template, Text, Wikilink, ExternalLink, HTMLEntity

from . import textparse as tp

INFOBOX_NAMES = re.compile(
    r"^\s*(?:template:)?\s*(infobox[ _]+(military[ _]+conflict|battle|war|conflict|military[ _]+engagement)|warbox)\s*$",
    re.I)

# Templates whose output we never want (citations, notes, maintenance tags).
_DROP = re.compile(
    r"^(cite|citation|sfn|harv|harvnb|efn|refn|ref|r$|rp$|cn$|citation needed|fact$|clarify|"
    r"dubious|by whom|which|when|who|according to whom|vague|verify|failed verification|"
    r"better source|page needed|full citation|nbsp$|note|notetag|nb\d*$|lower|upper|"
    r"increase|decrease|steady|coord|anchor|webarchive|dead link|disputed|clarification|"
    r"update|as of|lang-|ill$|interlanguage|flagdeco|small caps)", re.I)
_FLAG = re.compile(r"^(flag|flagicon|flagcountry|flagu|flagdeco|flag ?icon|army|navy|air ?force|"
                   r"flagstate|country data|flag image)", re.I)
_LIST = re.compile(r"^(plainlist|plain list|unbulleted list|ubl|ubil|flatlist|flat list|hlist|"
                   r"bulleted list|blist|collapsible list|enum|endplainlist|startplainlist|tree list|"
                   r"vunblist|indented plainlist|br separated entries)$", re.I)
_MARKERS = {"kia": " (KIA)", "wia": " (WIA)", "pow": " (POW)", "executed": " (executed)",
            "dow": " (DOW)", "mia": " (MIA)", "surrendered": " (surrendered)"}
_CHARS = {"ndash": "–", "snd": " – ", "spaced ndash": " – ", "mdash": "—", "-": "\n", "•": " • ",
          "dot": " · ", "·": " · ", "nbsp": " ", "thinsp": "", "break": "\n", "clear": "",
          "c.": "c. ", "circa": "c. ", "c": "c. ", "bc": "BC", "bce": "BCE", "ad": "AD"}


def _tname(t: Template) -> str:
    return str(t.name).strip().replace("_", " ")


def _positional(t: Template) -> list:
    return [p.value for p in t.params if not p.showkey]


def flatten(code) -> str:
    """Render wikicode to readable plain text (keeping list items on separate lines)."""
    if code is None:
        return ""
    if isinstance(code, str):
        code = mwp.parse(code)
    out: list[str] = []
    for node in code.nodes:
        if isinstance(node, Text):
            out.append(str(node))
        elif isinstance(node, HTMLEntity):
            out.append(node.normalize())
        elif isinstance(node, Comment):
            continue
        elif isinstance(node, Wikilink):
            title = str(node.title).strip()
            if re.match(r"^(file|image|category|media):", title, re.I):
                continue
            out.append(flatten(node.text) if node.text is not None else title.lstrip(":").split("#")[0])
        elif isinstance(node, ExternalLink):
            out.append(flatten(node.title) if node.title else "")
        elif isinstance(node, Tag):
            tag = str(node.tag).lower()
            if tag in ("ref", "references", "gallery", "math"):
                continue
            if tag in ("br", "hr"):
                out.append("\n")
                continue
            if tag == "li":
                out.append("\n")
            if node.contents is not None:
                out.append(flatten(node.contents))
            if tag in ("p", "div", "li", "ul", "ol"):
                out.append("\n")
        elif isinstance(node, Template):
            name = _tname(node)
            low = name.lower()
            if low in _MARKERS:
                out.append(_MARKERS[low])
            elif low in _CHARS:
                out.append(_CHARS[low])
            elif _LIST.match(name):
                for v in _positional(node):
                    out.append("\n" + flatten(v))
                out.append("\n")
            elif _FLAG.match(name):
                pos = _positional(node)
                if pos:
                    out.append(" " + flatten(pos[0]).strip() + " ")
            elif _DROP.match(name):
                continue
            elif low.startswith("lang") or low in ("transl", "transliteration", "nihongo"):
                pos = _positional(node)
                if pos:
                    out.append(flatten(pos[-1] if low != "nihongo" else pos[0]))
            elif low in ("convert", "cvt"):
                pos = _positional(node)
                if len(pos) >= 2:
                    out.append(f"{flatten(pos[0])} {flatten(pos[1])}")
            else:
                pos = _positional(node)
                if pos:
                    out.append(" ".join(flatten(v) for v in pos))
        else:
            out.append(str(node))
    text = html.unescape("".join(out))
    text = re.sub(r"'''?", "", text)
    text = re.sub(r"^\s*[*#:;]+\s*", "", text, flags=re.M)  # wiki list markers
    return tp.clean(text)


def _norm_title(title: str) -> str:
    title = html.unescape(title).split("#")[0].replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip().lstrip(":")
    return title[:1].upper() + title[1:] if title else title


def links(code) -> list[str]:
    """All article links in a field (in order, unique), skipping refs and files."""
    if code is None:
        return []
    seen, out = set(), []

    def walk(wc):
        for node in wc.nodes:
            if isinstance(node, Wikilink):
                t = str(node.title).strip()
                if re.match(r"^(file|image|category|media|wikt|wiktionary|w|d|s|commons|[a-z]{2,3}):", t, re.I):
                    continue
                t = _norm_title(t)
                if t and t not in seen:
                    seen.add(t)
                    out.append(t)
            elif isinstance(node, Tag):
                if str(node.tag).lower() == "ref" or node.contents is None:
                    continue
                walk(node.contents)
            elif isinstance(node, Template):
                if _DROP.match(_tname(node)):
                    continue
                for p in node.params:
                    walk(p.value)

    walk(code if not isinstance(code, str) else mwp.parse(code))
    return out


def flag_names(code) -> list[str]:
    """Country names given to {{flag}}/{{flagicon}}-style templates."""
    out = []
    for t in (code.filter_templates(recursive=True) if code is not None else []):
        if _FLAG.match(_tname(t)):
            pos = _positional(t)
            if pos:
                out.append(str(pos[0]).strip())
    return out


def find_infobox(wikitext: str):
    code = mwp.parse(wikitext)
    for t in code.filter_templates(recursive=False):
        if INFOBOX_NAMES.match(str(t.name)):
            return t
    for t in code.filter_templates(recursive=True):
        if INFOBOX_NAMES.match(str(t.name)):
            return t
    return None


_SIDE_FIELD = re.compile(r"^(combatant|commander|strength|casualties|units)(\d)([a-z]?)$", re.I)

WAR_TITLE = re.compile(r"\b(Wars?|Conflict|Revolution|Rebellion|Revolt|Uprising|Insurgency|Insurrection|"
                       r"Crusade|Crisis|Occupation|Intervention|Emergency|Troubles|Mutiny|Jihad|Reconquista|"
                       r"Conquest|Unification|Partition|Genocide|Massacre|Pogrom|Riots?)\b")
BATTLE_TITLE = re.compile(r"\b(Battles?|Siege|Sieges|Action|Raid|Assault|Skirmish|Engagement|Ambush|"
                          r"Operation|Capture|Fall|Sack|Storming|Relief|Bombardment|Landing|Defense|Defence|"
                          r"Attack|Clash|Combat|Encounter|Incident|Recapture|Expedition|Offensive|Campaign)\b")


def kind_of(title: str, partof: str) -> str:
    """Rough classification: battle, siege, naval, operation, campaign or war."""
    if re.search(r"^(Siege|Sieges|Sack|Fall|Storming|Relief|Blockade) of\b", title):
        return "siege"
    if re.search(r"\b(Naval|Sea)\b", title) or re.search(r"^(Action|Raid) (of|off|at)\b", title):
        return "naval"
    if title.startswith("Operation "):
        return "operation"
    if re.search(r"\b(Campaign|Offensive|Expedition|Invasion)\b", title):
        return "campaign"
    if WAR_TITLE.search(title) and not BATTLE_TITLE.search(title):
        return "war"
    if not partof and WAR_TITLE.search(title):
        return "war"
    return "battle"


def parse_battle(title: str, wikitext: str) -> dict | None:
    """Extract one battle from an article's wikitext. Returns None if no usable infobox."""
    box = find_infobox(wikitext) if not isinstance(wikitext, Template) else wikitext
    if box is None:
        return None
    fields: dict[str, mwp.wikicode.Wikicode] = {}
    sides: dict[int, dict] = {}
    for p in box.params:
        key = str(p.name).strip().lower().replace(" ", "")
        m = _SIDE_FIELD.match(key)
        if m:
            kind, num = m.group(1).lower(), int(m.group(2))
            side = sides.setdefault(num, {"combatant": [], "commander": [], "strength": [], "casualties": [], "units": []})
            side[kind].append(p.value)
        else:
            fields[key] = p.value

    def field(name):
        return flatten(fields.get(name)) if name in fields else ""

    partof = field("partof")
    record = {
        "title": title,
        "name": field("conflict") or title,
        "partof": partof,
        "date": field("date"),
        "place": field("place"),
        "result": field("result"),
        "result_links": links(fields.get("result")),
        "year": tp.parse_year(field("date")),
        "kind": kind_of(title, partof),
        "sides": [],
    }
    if record["year"] is None:
        m = re.search(r"\((\d{3,4})\)", title)
        if m:
            record["year"] = int(m.group(1))

    for num in sorted(sides):
        s = sides[num]
        # The main field (combatant1) comes first; lettered fields (combatant1a) follow.
        comb_text = "\n".join(flatten(v) for v in s["combatant"])
        comb_links = [l for v in s["combatant"] for l in links(v)]
        flags = [f for v in s["combatant"] for f in flag_names(v)]
        cmd_links = []
        for v in s["commander"]:
            for l in links(v):
                if l not in cmd_links:
                    cmd_links.append(l)
        cmd_text = "\n".join(flatten(v) for v in s["commander"])
        strength_text = "\n".join(flatten(v) for v in s["strength"][:1])  # main strength field only
        record["sides"].append({
            "combatant": comb_text,
            "combatant_links": comb_links,
            "flags": flags,
            "commander_links": cmd_links,
            "commander_text": cmd_text,
            "strength_text": strength_text,
            "strength": tp.parse_strength(strength_text),
        })
    # Collapse to sides that actually exist
    record["sides"] = [s for s in record["sides"] if s["combatant"] or s["commander_links"]]
    resolve_outcome(record)
    return record


def resolve_outcome(record: dict) -> None:
    """Set record['winner'] to a side index, -1 for a draw, or None if unknown."""
    kind, phrase = tp.parse_result(record["result"])
    record["result_kind"] = kind
    record["result_phrase"] = phrase
    record["winner"] = None
    sides = record["sides"]
    if len(sides) != 2:
        return
    if kind == "draw":
        record["winner"] = -1
        return
    if kind not in ("victory", "defeat"):
        return
    side_tokens, side_links, cmd_tokens = [], [], []
    for s in sides:
        toks = tp.tokens(s["combatant"]) | tp.tokens(" ".join(s["flags"])) | tp.tokens(" ".join(s["combatant_links"]))
        side_tokens.append(toks)
        side_links.append(set(s["combatant_links"]))
        cmd_tokens.append(tp.tokens(s["commander_text"]) | tp.tokens(" ".join(s["commander_links"])))
    # Only use result links whose words appear in the matched phrase
    phrase_links = [l for l in record["result_links"] if tp.tokens(l) & tp.tokens(phrase)]
    idx = tp.match_side(phrase, side_tokens, phrase_links, side_links)
    if idx is None:
        # "Braccio da Montone's defeat": the phrase may name a commander
        idx = tp.match_side(phrase, cmd_tokens)
    if idx is None and re.fullmatch(r"(coalition|allied|allies|anglo-allied)", phrase.strip(), re.I):
        # The side listing several belligerents is the coalition
        n = [max(len(s["flags"]), len(s["combatant_links"]), s["combatant"].count("\n") + 1) for s in sides]
        if n[0] != n[1] and max(n) >= 2:
            idx = n.index(max(n))
    if idx is None:
        return
    record["winner"] = idx if kind == "victory" else 1 - idx
