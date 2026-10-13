"""Run with:  python -m pytest -q"""
from scraper import infobox, textparse as tp

AUSTERLITZ = """{{Short description|1805 battle}}
{{Infobox military conflict
| conflict    = Battle of Austerlitz
| partof      = the [[War of the Third Coalition]]
| image       = [[File:La bataille d'Austerlitz.jpg|300px]]
| date        = 2 December 1805
| place       = [[Slavkov u Brna|Austerlitz]], [[Moravia]], [[Austrian Empire]]
| result      = Decisive [[First French Empire|French]] victory<ref>Chandler p. 432</ref>
| combatant1  = {{flagcountry|First French Empire}}
| combatant2  = {{flag|Russian Empire}}<br />{{flagcountry|Austrian Empire}}
| commander1  = {{flagicon|First French Empire}} [[Napoleon]]<br />{{flagicon|First French Empire}} [[Jean-de-Dieu Soult]]
| commander2  = {{plainlist|
* {{flagicon|Russian Empire}} [[Alexander I of Russia|Alexander I]]
* {{flagicon|Russian Empire}} [[Mikhail Kutuzov]]
* {{flagicon|Austrian Empire}} [[Francis II, Holy Roman Emperor|Francis II]]
}}
| strength1   = 65,000–75,000<ref name=a/>
| strength2   = 84,000–95,000<br />318 guns
| casualties1 = 1,305 killed
}}
'''Battle of Austerlitz''' was ..."""

WATERLOO = """{{Infobox military conflict
| conflict = Battle of Waterloo
| partof = the [[War of the Seventh Coalition]]
| date = 18 June 1815
| result = Coalition victory, end of the [[Hundred Days]]
| combatant1 = {{flagicon|France}} [[First French Empire|French Empire]]
| combatant2 = {{plainlist|
* {{flag|United Kingdom of Great Britain and Ireland|name=United Kingdom}}
* {{flag|Kingdom of Prussia}}
* {{flag|United Kingdom of the Netherlands}}
}}
| commander1 = [[Napoleon]]<br />[[Michel Ney]]
| commander2 = [[Arthur Wellesley, 1st Duke of Wellington|Duke of Wellington]]<br />[[Gebhard Leberecht von Blücher]]
| strength1 = '''Total:''' 73,000
| strength2 = '''Total:''' 118,000
}}"""

CANNAE = """{{Infobox military conflict
| conflict = Battle of Cannae
| partof = the [[Second Punic War]]
| date = 2 August 216 BC
| result = [[Carthage|Carthaginian]] victory
| combatant1 = [[Ancient Carthage|Carthage]]
| combatant2 = [[Roman Republic|Rome]]
| commander1 = [[Hannibal]]<br>[[Hasdrubal (Barcid general)|Hasdrubal]]
| commander2 = [[Gaius Terentius Varro]]<br>[[Lucius Aemilius Paullus (consul 216 BC)|Lucius Aemilius Paullus]]{{KIA}}
| strength1 = 40,000 infantry<br>10,000 cavalry
| strength2 = 80,000 infantry<br>6,400 cavalry
}}"""

DRAW = """{{Infobox military conflict
| conflict = Battle of Borodino
| date = {{OldStyleDate|7 September|1812|26 August}}
| result = Indecisive<ref>x</ref>
| combatant1 = {{flagicon|France}} [[First French Empire|French Empire]]
| combatant2 = {{flagicon|Russian Empire}} [[Russian Empire]]
| commander1 = [[Napoleon]]
| commander2 = [[Mikhail Kutuzov]]
| strength1 = 130,000
| strength2 = 120,000
}}"""

DEFEAT_FORM = """{{Infobox military conflict
| conflict = Battle of Example
| partof = [[Example War]]
| date = c. 1450
| result = [[Ottoman Empire|Ottoman]] defeat
| combatant1 = [[Ottoman Empire]]
| combatant2 = [[Kingdom of Hungary]]
| commander1 = [[Murad II]]
| commander2 = [[John Hunyadi]]
}}"""


def test_austerlitz():
    b = infobox.parse_battle("Battle of Austerlitz", AUSTERLITZ)
    assert b["year"] == 1805
    assert b["kind"] == "battle"
    assert b["winner"] == 0
    assert b["sides"][0]["commander_links"] == ["Napoleon", "Jean-de-Dieu Soult"]
    assert b["sides"][1]["commander_links"][:2] == ["Alexander I of Russia", "Mikhail Kutuzov"]
    assert b["sides"][0]["strength"] == 70000
    assert b["sides"][1]["strength"] == 89500   # guns ignored


def test_waterloo_coalition_and_totals():
    b = infobox.parse_battle("Battle of Waterloo", WATERLOO)
    assert b["winner"] == 1
    assert b["sides"][0]["strength"] == 73000
    assert b["sides"][1]["strength"] == 118000
    assert "Arthur Wellesley, 1st Duke of Wellington" in b["sides"][1]["commander_links"]


def test_cannae_bc_and_unit_sum():
    b = infobox.parse_battle("Battle of Cannae", CANNAE)
    assert b["year"] == -216
    assert b["winner"] == 0
    assert b["sides"][0]["strength"] == 50000
    assert b["sides"][1]["strength"] == 86400


def test_draw_and_defeat():
    assert infobox.parse_battle("Battle of Borodino", DRAW)["winner"] == -1
    b = infobox.parse_battle("Battle of Example", DEFEAT_FORM)
    assert b["winner"] == 1 and b["year"] == 1450


def test_kind():
    assert infobox.kind_of("Siege of Vienna", "") == "siege"
    assert infobox.kind_of("Napoleonic Wars", "") == "war"
    assert infobox.kind_of("Battle of the Bulge", "World War II") == "battle"
    assert infobox.kind_of("Operation Overlord", "") == "operation"


def test_text_parsers():
    assert tp.parse_year("214–212 BC") == -214
    assert tp.parse_year("June 18, 1815") == 1815
    assert tp.parse_year("AD 9") == 9
    assert tp.parse_year("Late 4th century BC") == -350
    assert tp.parse_strength("c. 30,000") == 30000
    assert tp.parse_strength("Between 200.000 and 300.000") == 250000
    assert tp.parse_strength("9 legions") == 45000
    assert tp.parse_strength("20 ships of the line") is None
    assert tp.parse_result("Tactical draw; strategic British victory") == ("draw", "")
    assert tp.parse_result("Decisive Pyrrhic Roman victory") == ("victory", "Roman")
    assert tp.parse_result("Victory for the Union") == ("victory", "Union")
    assert tp.parse_result("See Aftermath") == ("unknown", "")
