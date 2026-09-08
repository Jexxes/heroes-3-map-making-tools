#!/usr/bin/env python3
"""
h3m.py - a parser for Heroes of Might and Magic III map files (.h3m)

Supports RoE (0x0E), Armageddon's Blade (0x15) and Shadow of Death (0x1C).

Usage:
    python3 h3m.py MAP.h3m                     # human-readable summary
    python3 h3m.py MAP.h3m --objects           # + full object list w/ coords
    python3 h3m.py MAP.h3m --json out.json     # full structured dump
    python3 h3m.py MAP.h3m --csv out.csv       # objects as x,y,z,type,...
    python3 h3m.py MAP.h3m --terrain-csv t.csv # per-tile terrain dump

Library use:
    from h3m import parse_file
    m = parse_file("MAP.h3m")
    for o in m["objects"]:
        print(o["x"], o["y"], o["z"], o["name"])
"""

import argparse
import csv
import gzip
import json
import os
import struct
import zlib
from collections import Counter

# --------------------------------------------------------------------------
# Format versions
# --------------------------------------------------------------------------
ROE, AB, SOD, HOTA, WOG = 0x0E, 0x15, 0x1C, 0x20, 0x33
VERSION_NAMES = {
    ROE: "Restoration of Erathia",
    AB: "Armageddon's Blade",
    SOD: "Shadow of Death",
    HOTA: "Horn of the Abyss",
    WOG: "Wake of Gods",
}

# --------------------------------------------------------------------------
# Lookup tables.  IDs are authoritative (they come straight from the file);
# names are a convenience mapping.
# --------------------------------------------------------------------------
PLAYERS = ["Red", "Blue", "Tan", "Green", "Orange", "Purple", "Teal", "Pink"]
PLAYER_NONE = 255

def player_name(v):
    if v in (255, -1, 0xFFFFFFFF):
        return "Neutral/None"
    return PLAYERS[v] if 0 <= v < 8 else f"Player{v}"

DIFFICULTY = ["Easy", "Normal", "Hard", "Expert", "Impossible"]

TERRAIN = ["Dirt", "Sand", "Grass", "Snow", "Swamp", "Rough", "Subterranean",
           "Lava", "Water", "Rock"]

RIVER = ["None", "Clear", "Icy", "Muddy", "Lava"]
ROAD = ["None", "Dirt", "Gravel", "Cobblestone"]

RESOURCES = ["Wood", "Mercury", "Ore", "Sulfur", "Crystal", "Gems", "Gold"]

FACTIONS = ["Castle", "Rampart", "Tower", "Inferno", "Necropolis", "Dungeon",
            "Stronghold", "Fortress", "Conflux", "Neutral"]

PRIMARY_SKILLS = ["Attack", "Defense", "Spell Power", "Knowledge"]

SEC_SKILLS = [
    "Pathfinding", "Archery", "Logistics", "Scouting", "Diplomacy", "Navigation",
    "Leadership", "Wisdom", "Mysticism", "Luck", "Ballistics", "Eagle Eye",
    "Necromancy", "Estates", "Fire Magic", "Air Magic", "Water Magic",
    "Earth Magic", "Scholar", "Tactics", "Artillery", "Learning", "Offence",
    "Armorer", "Intelligence", "Sorcery", "Resistance", "First Aid",
]
SEC_LEVELS = ["None", "Basic", "Advanced", "Expert"]

AI_TACTIC = ["Random", "Warrior", "Builder", "Explorer"]

FORMATION = ["Spread", "Grouped"]

MONSTER_CHARACTER = {0: "Compliant", 1: "Friendly", 2: "Aggressive",
                     3: "Hostile", 4: "Savage"}

VICTORY_CONDITIONS = {
    0: "Acquire artifact", 1: "Accumulate creatures", 2: "Accumulate resources",
    3: "Upgrade town", 4: "Build Grail structure", 5: "Defeat hero",
    6: "Capture town", 7: "Defeat monster", 8: "Flag all creature dwellings",
    9: "Flag all mines", 10: "Transport artifact", 255: "Defeat all enemies (standard)",
}
LOSS_CONDITIONS = {
    0: "Lose town", 1: "Lose hero", 2: "Time expires",
    255: "Lose all towns and heroes (standard)",
}

QUEST_MISSIONS = {
    0: "None", 1: "Reach hero level", 2: "Reach primary skill level",
    3: "Defeat specific hero", 4: "Defeat specific monster", 5: "Bring artifacts",
    6: "Bring creatures", 7: "Bring resources", 8: "Be specific hero",
    9: "Be specific player",
}
SEER_REWARDS = {
    0: "Nothing", 1: "Experience", 2: "Spell points", 3: "Morale", 4: "Luck",
    5: "Resource", 6: "Primary skill", 7: "Secondary skill", 8: "Artifact",
    9: "Spell", 10: "Creatures",
}

# Object class IDs (the "type" field of an object template)
OBJECTS = {
    0: "Nothing", 1: "Altar of Sacrifice(?)", 2: "Altar of Sacrifice",
    3: "Anchor Point", 4: "Arena", 5: "Artifact", 6: "Pandora's Box",
    7: "Black Market", 8: "Boat", 9: "Border Guard", 10: "Keymaster's Tent",
    11: "Buoy", 12: "Campfire", 13: "Cartographer", 14: "Swan Pond",
    15: "Cover of Darkness", 16: "Creature Bank", 17: "Creature Generator 1",
    18: "Creature Generator 2", 19: "Creature Generator 3",
    20: "Creature Generator 4", 21: "Cursed Ground", 22: "Corpse",
    23: "Marletto Tower", 24: "Derelict Ship", 25: "Dragon Utopia", 26: "Event",
    27: "Eye of the Magi", 28: "Faerie Ring", 29: "Flotsam",
    30: "Fountain of Fortune", 31: "Fountain of Youth",
    32: "Garden of Revelation", 33: "Garrison", 34: "Hero", 35: "Hill Fort",
    36: "Grail", 37: "Hut of the Magi", 38: "Idol of Fortune", 39: "Lean To",
    41: "Library of Enlightenment", 42: "Lighthouse",
    43: "Monolith One Way Entrance", 44: "Monolith One Way Exit",
    45: "Monolith Two Way", 46: "Magic Plains", 47: "School of Magic",
    48: "Magic Spring", 49: "Magic Well", 50: "Market of Time",
    51: "Mercenary Camp", 52: "Mermaid", 53: "Mine", 54: "Monster",
    55: "Mystical Garden", 56: "Oasis", 57: "Obelisk", 58: "Redwood Observatory",
    59: "Ocean Bottle", 60: "Pillar of Fire", 61: "Star Axis", 62: "Prison",
    63: "Pyramid", 64: "Rally Flag", 65: "Random Artifact",
    66: "Random Treasure Artifact", 67: "Random Minor Artifact",
    68: "Random Major Artifact", 69: "Random Relic", 70: "Random Hero",
    71: "Random Monster", 72: "Random Monster level 1",
    73: "Random Monster level 2", 74: "Random Monster level 3",
    75: "Random Monster level 4", 76: "Random Resource", 77: "Random Town",
    78: "Refugee Camp", 79: "Resource", 80: "Sanctuary", 81: "Scholar",
    82: "Sea Chest", 83: "Seer's Hut", 84: "Crypt", 85: "Shipwreck",
    86: "Shipwreck Survivor", 87: "Shipyard", 88: "Shrine of Magic Incantation",
    89: "Shrine of Magic Gesture", 90: "Shrine of Magic Thought", 91: "Sign",
    92: "Sirens", 93: "Spell Scroll", 94: "Stables", 95: "Tavern", 96: "Temple",
    97: "Den of Thieves", 98: "Town", 99: "Trading Post", 100: "Learning Stone",
    101: "Treasure Chest", 102: "Tree of Knowledge", 103: "Subterranean Gate",
    104: "University", 105: "Wagon", 106: "War Machine Factory",
    107: "School of War", 108: "Warrior's Tomb", 109: "Water Wheel",
    110: "Watering Hole", 111: "Whirlpool", 112: "Windmill", 113: "Witch Hut",
    114: "Brush", 115: "Bush", 116: "Cactus", 117: "Canyon", 118: "Crater",
    119: "Dead Vegetation", 120: "Flowers", 121: "Frozen Lake", 122: "Hedge",
    123: "Hill", 124: "Hole", 125: "Kelp", 126: "Lake", 127: "Lava Flow",
    128: "Lava Lake", 129: "Mushrooms", 130: "Log", 131: "Mandrake",
    132: "Moss", 133: "Mound", 134: "Mountain", 135: "Oak Trees", 136: "Outcropping",
    137: "Pine Trees", 138: "Plant", 139: "River Delta",
    143: "River Delta", 144: "Sand Dune", 145: "Sand Pit", 146: "Shrub", 147: "Rock",
    148: "Stalagmite", 149: "Sand Pit", 150: "Tar Pit", 151: "Skull",
    152: "Vine", 153: "Scenery", 154: "Volcano", 155: "Palm Trees",
    156: "Yucca Trees", 157: "Reef",

     162: "Random Monster level 5", 163: "Random Monster level 6",
    164: "Random Monster level 7", 165: "Cache", 166: "Ruins",
    177: "Lake", 199: "Swamp Trees", 206: "Scenery (desert)",
    158: "Volcano",
    161: "Reef",
    207: "Scenery (dirt)",
    208: "Scenery (grass)",
    209: "Scenery (rough)",
    210: "Scenery (subterranean)",
    211: "Scenery (swamp)",
    212: "Border Gate", 213: "Freelancer's Guild", 214: "Hero Placeholder",
    215: "Quest Guard", 216: "Random Dwelling", 217: "Random Dwelling (level)",
    218: "Random Dwelling (faction)", 219: "Garrison (vertical)",
    220: "Abandoned Mine", 221: "Trading Post (snow)", 222: "Clover Field",
    223: "Cursed Ground2", 224: "Evil Fog", 225: "Favorable Winds",
    226: "Fiery Fields", 227: "Holy Ground", 228: "Lucid Pools",
    229: "Magic Clouds", 230: "Magic Plains2", 231: "Rocklands",
}


# Creature dwellings (object id 17). The subtype maps one-to-one onto a
# dwelling sprite, and through it to the creature the dwelling produces.
# Seven subtypes whose sprite could not be decoded confidently are left out
# on purpose: they fall back to the sprite name rather than get a guess.
DWELLING_CREATURE = {
    0: "Basilisk", 1: "Behemoth", 2: "Beholder", 3: "Black Knight",
    4: "Bone Dragon", 5: "Cavalier", 6: "Centaur", 7: "Air Elemental",
    8: "Angel", 9: "Cyclops", 10: "Devil", 11: "Serpent Fly", 12: "Dwarf",
    13: "Earth Elemental", 14: "Efreeti", 15: "Wood Elf",
    16: "Fire Elemental", 17: "Stone Gargoyle", 18: "Genie", 19: "Wolf Rider",
    20: "Gnoll", 21: "Goblin", 22: "Gog", 23: "Gorgon", 24: "Green Dragon",
    25: "Griffin", 26: "Harpy", 27: "Hell Hound", 28: "Hydra", 29: "Imp",
    30: "Lizardman", 31: "Mage", 32: "Manticore", 33: "Medusa",
    34: "Minotaur", 35: "Monk", 36: "Naga", 37: "Demon", 38: "Ogre",
    39: "Orc", 40: "Pit Fiend", 41: "Red Dragon", 42: "Roc", 43: "Gremlin",
    44: "Giant", 45: "Dendroid Guard", 46: "Troglodyte",
    47: "Water Elemental", 48: "Wight", 49: "Wyvern", 50: "Pegasus",
    51: "Unicorn", 52: "Lich", 53: "Vampire", 54: "Skeleton",
    55: "Walking Dead", 56: "Pikeman", 57: "Archer", 58: "Swordsman",
    59: "Pixie", 61: "Firebird", 62: "Azure Dragon", 63: "Crystal Dragon",
    64: "Faerie Dragon", 65: "Rust Dragon", 66: "Enchanter",
    67: "Sharpshooter", 73: "Halfling", 74: "Peasant", 75: "Boar",
    77: "Nomad", 78: "Rogue", 79: "Troll",
}

# Object id 20 covers the two multi-creature conflux dwellings.
DWELLING_GROUP = {0: "Elemental Conflux", 1: "Golem Factory"}


def dwelling_name(object_id, subid, def_name=""):
    """Readable name for a creature dwelling, or None if it is not one."""
    if object_id == 17:
        who = DWELLING_CREATURE.get(subid)
        if who:
            return f"{who} dwelling"
        sprite = (def_name or "").rsplit("/", 1)[-1]
        return f"Creature dwelling ({sprite})" if sprite else None
    if object_id == 20:
        return DWELLING_GROUP.get(subid, "Creature dwelling")
    if object_id in (18, 19):
        return "Creature dwelling (upgraded)"
    return None


MINE_SUBTYPE = {0: "Sawmill (Wood)", 1: "Alchemist's Lab (Mercury)",
                2: "Ore Pit (Ore)", 3: "Sulfur Dune (Sulfur)",
                4: "Crystal Cavern (Crystal)", 5: "Gem Pond (Gems)",
                6: "Gold Mine (Gold)", 7: "Abandoned Mine"}

CREATURES = [
    "Pikeman", "Halberdier", "Archer", "Marksman", "Griffin", "Royal Griffin",
    "Swordsman", "Crusader", "Monk", "Zealot", "Cavalier", "Champion",
    "Angel", "Archangel",
    "Centaur", "Centaur Captain", "Dwarf", "Battle Dwarf", "Wood Elf",
    "Grand Elf", "Pegasus", "Silver Pegasus", "Dendroid Guard",
    "Dendroid Soldier", "Unicorn", "War Unicorn", "Green Dragon",
    "Gold Dragon",
    "Gremlin", "Master Gremlin", "Stone Gargoyle", "Obsidian Gargoyle",
    "Stone Golem", "Iron Golem", "Mage", "Arch Mage", "Genie", "Master Genie",
    "Naga", "Naga Queen", "Giant", "Titan",
    "Imp", "Familiar", "Gog", "Magog", "Hell Hound", "Cerberus", "Demon",
    "Horned Demon", "Pit Fiend", "Pit Lord", "Efreeti", "Efreet Sultan",
    "Devil", "Arch Devil",
    "Skeleton", "Skeleton Warrior", "Walking Dead", "Zombie", "Wight",
    "Wraith", "Vampire", "Vampire Lord", "Lich", "Power Lich", "Black Knight",
    "Dread Knight", "Bone Dragon", "Ghost Dragon",
    "Troglodyte", "Infernal Troglodyte", "Harpy", "Harpy Hag", "Beholder",
    "Evil Eye", "Medusa", "Medusa Queen", "Minotaur", "Minotaur King",
    "Manticore", "Scorpicore", "Red Dragon", "Black Dragon",
    "Goblin", "Hobgoblin", "Wolf Rider", "Wolf Raider", "Orc", "Orc Chieftain",
    "Ogre", "Ogre Mage", "Roc", "Thunderbird", "Cyclops", "Cyclops King",
    "Behemoth", "Ancient Behemoth",
    "Gnoll", "Gnoll Marauder", "Lizardman", "Lizard Warrior", "Gorgon",
    "Mighty Gorgon", "Serpent Fly", "Dragon Fly", "Basilisk", "Greater Basilisk",
    "Wyvern", "Wyvern Monarch", "Hydra", "Chaos Hydra",
    "Air Elemental", "Earth Elemental", "Fire Elemental", "Water Elemental",
    "Gold Golem", "Diamond Golem", "Pixie", "Sprite", "Psychic Elemental",
    "Magic Elemental", "NOT USED", "Ice Elemental", "NOT USED (Magma)",
    "Magma Elemental", "NOT USED (Storm)", "Storm Elemental",
    "NOT USED (Energy)", "Energy Elemental", "Firebird", "Phoenix",
    "Azure Dragon", "Crystal Dragon", "Faerie Dragon", "Rust Dragon",
    "Enchanter", "Sharpshooter", "Halfling", "Peasant", "Boar", "Mummy",
    "Nomad", "Rogue", "Troll",
    "Catapult", "Ballista", "First Aid Tent", "Ammo Cart", "Arrow Tower",
]


ARTIFACTS = [
    "Spellbook", "Spell Scroll", "Grail", "Catapult", "Ballista", "Ammo Cart",
    "First Aid Tent", "Centaur Axe", "Blackshard of the Dead Knight",
    "Greater Gnoll's Flail", "Ogre's Club of Havoc", "Sword of Hellfire",
    "Titan's Gladius", "Shield of the Dwarven Lords", "Shield of the Yawning Dead",
    "Buckler of the Gnoll King", "Targ of the Rampaging Ogre", "Shield of the Damned",
    "Sentinel's Shield", "Helm of the Alabaster Unicorn", "Skull Helmet",
    "Helm of Chaos", "Crown of the Supreme Magi", "Hellstorm Helmet",
    "Thunder Helmet", "Breastplate of Petrified Wood", "Rib Cage",
    "Scales of the Greater Basilisk", "Tunic of the Cyclops King",
    "Breastplate of Brimstone", "Titan's Cuirass", "Armor of Wonder",
    "Sandals of the Saint", "Celestial Necklace of Bliss",
    "Lion's Shield of Courage", "Sword of Judgement",
    "Helm of Heavenly Enlightenment", "Quiet Eye of the Dragon",
    "Red Dragon Flame Tongue", "Dragon Scale Shield", "Dragon Scale Armor",
    "Dragonbone Greaves", "Dragon Wing Tabard", "Necklace of Dragonteeth",
    "Crown of Dragontooth", "Still Eye of the Dragon", "Clover of Fortune",
    "Cards of Prophecy", "Ladybird of Luck", "Badge of Courage", "Crest of Valor",
    "Glyph of Gallantry", "Speculum", "Spyglass", "Amulet of the Undertaker",
    "Vampire's Cowl", "Dead Man's Boots", "Garniture of Interference",
    "Surcoat of Counterpoise", "Boots of Polarity", "Bow of Elven Cherrywood",
    "Bowstring of the Unicorn's Mane", "Angel Feather Arrows",
    "Bird of Perception", "Stoic Watchman", "Emblem of Cognizance",
    "Statesman's Medal", "Diplomat's Ring", "Ambassador's Sash",
    "Ring of the Wayfarer", "Equestrian's Gloves", "Necklace of Ocean Guidance",
    "Angel Wings", "Charm of Mana", "Talisman of Mana", "Mystic Orb of Mana",
    "Collar of Conjuring", "Ring of Conjuring", "Cape of Conjuring",
    "Orb of the Firmament", "Orb of Silt", "Orb of Tempestuous Fire",
    "Orb of Driving Rain", "Recanter's Cloak", "Spirit of Oppression",
    "Hourglass of the Evil Hour", "Tome of Fire Magic", "Tome of Air Magic",
    "Tome of Water Magic", "Tome of Earth Magic", "Boots of Levitation",
    "Golden Bow", "Sphere of Permanence", "Orb of Vulnerability",
    "Ring of Vitality", "Ring of Life", "Vial of Lifeblood",
    "Necklace of Swiftness", "Boots of Speed", "Cape of Velocity",
    "Pendant of Dispassion", "Pendant of Second Sight", "Pendant of Holiness",
    "Pendant of Life", "Pendant of Death", "Pendant of Free Will",
    "Pendant of Negativity", "Pendant of Total Recall", "Pendant of Courage",
    "Everflowing Crystal Cloak", "Ring of Infinite Gems",
    "Everpouring Vial of Mercury", "Inexhaustible Cart of Ore",
    "Eversmoking Ring of Sulfur", "Inexhaustible Cart of Lumber",
    "Endless Sack of Gold", "Endless Bag of Gold", "Endless Purse of Gold",
    "Legs of Legion", "Loins of Legion", "Torso of Legion", "Arms of Legion",
    "Head of Legion", "Sea Captain's Hat", "Spellbinder's Hat",
    "Shackles of War", "Orb of Inhibition", "Vial of Dragon Blood",
    "Armageddon's Blade", "Angelic Alliance", "Cloak of the Undead King",
    "Elixir of Life", "Armor of the Damned", "Statue of Legion",
    "Power of the Dragon Father", "Titan's Thunder", "Admiral's Hat",
    "Bow of the Sharpshooter", "Wizard's Well", "Ring of the Magi",
    "Cornucopia",
]

SPELLS = [
    "Summon Boat", "Scuttle Boat", "Visions", "View Earth", "Disguise",
    "View Air", "Fly", "Water Walk", "Dimension Door", "Town Portal",
    "Quicksand", "Land Mine", "Force Field", "Fire Wall", "Earthquake",
    "Magic Arrow", "Ice Bolt", "Lightning Bolt", "Implosion", "Chain Lightning",
    "Frost Ring", "Fireball", "Inferno", "Meteor Shower", "Death Ripple",
    "Destroy Undead", "Armageddon", "Shield", "Air Shield", "Fire Shield",
    "Protection from Air", "Protection from Fire", "Protection from Water",
    "Protection from Earth", "Anti-Magic", "Dispel", "Magic Mirror", "Cure",
    "Resurrection", "Animate Dead", "Sacrifice", "Bless", "Curse", "Bloodlust",
    "Precision", "Weakness", "Stone Skin", "Disrupting Ray", "Prayer", "Mirth",
    "Sorrow", "Fortune", "Misfortune", "Haste", "Slow", "Slayer", "Frenzy",
    "Titan's Lightning Bolt", "Counterstrike", "Berserk", "Hypnotize",
    "Forgetfulness", "Blind", "Teleport", "Remove Obstacle", "Clone",
    "Fire Elemental", "Earth Elemental", "Water Elemental", "Air Elemental",
]

HEROES = [
    "Orrin", "Valeska", "Edric", "Sylvia", "Lord Haart", "Sorsha", "Christian",
    "Tyris", "Rion", "Adela", "Cuthbert", "Adelaide", "Ingham", "Sanya",
    "Loynis", "Caitlin",
    "Mephala", "Ufretin", "Jenova", "Ryland", "Thorgrim", "Ivor", "Clancy",
    "Kyrre", "Coronius", "Uland", "Elleshar", "Gem", "Malcom", "Melodia",
    "Alagar", "Aeris",
    "Piquedram", "Thane", "Josephine", "Neela", "Torosar", "Fafner", "Rissa",
    "Iona", "Astral", "Halon", "Serena", "Daremyth", "Theodorus", "Solmyr",
    "Cyra", "Aine",
    "Fiona", "Rashka", "Marius", "Ignatius", "Octavia", "Calh", "Pyre",
    "Nymus", "Ayden", "Xyron", "Axsis", "Olema", "Calid", "Ash", "Zydar",
    "Xarfax",
    "Straker", "Vokial", "Moandor", "Charna", "Tamika", "Isra", "Clavius",
    "Galthran", "Septienna", "Aislinn", "Sandro", "Nimbus", "Thant", "Xsi",
    "Vidomina", "Nagash",
    "Lorelei", "Arlach", "Dace", "Ajit", "Damacon", "Gunnar", "Synca",
    "Shakti", "Alamar", "Jaegar", "Malekith", "Jeddite", "Geon", "Deemer",
    "Sephinroth", "Darkstorn",
    "Yog", "Gurnisson", "Jabarkas", "Shiva", "Gretchin", "Krellion",
    "Crag Hack", "Tyraxor", "Gird", "Vey", "Dessa", "Terek", "Zubin",
    "Gundula", "Oris", "Saurug",
    "Bron", "Drakon", "Wystan", "Tazar", "Alkin", "Korbac", "Gerwulf",
    "Broghild", "Mirlanda", "Rosic", "Voy", "Verdish", "Merist", "Styg",
    "Andra", "Tiva",
    "Pasis", "Thunar", "Ignissa", "Lacus", "Monere", "Erdamon", "Fiur",
    "Kalt", "Luna", "Brissa", "Ciele", "Labetha", "Inteus", "Aenain",
    "Gelare", "Grindan",
    "Sir Mullich", "Adrienne", "Catherine", "Dracon", "Gelu", "Kilgor",
    "Lord Haart (Death Knight)", "Mutare", "Roland", "Mutare Drake",
    "Boragus", "Xeron",
]


def aname(i):
    if i is None:
        return None
    return ARTIFACTS[i] if 0 <= i < len(ARTIFACTS) else f"Artifact#{i}"


def spname(i):
    if i is None or i in (255, 0xFFFFFFFF):
        return "Random"
    return SPELLS[i] if 0 <= i < len(SPELLS) else f"Spell#{i}"


def hname(i):
    if i is None or i == 255:
        return "Random"
    return HEROES[i] if 0 <= i < len(HEROES) else f"Hero#{i}"


# Town building bit indices (best-effort; SPECIAL_n differ per faction)
BUILDINGS = [
    "Mage Guild 1", "Mage Guild 2", "Mage Guild 3", "Mage Guild 4",
    "Mage Guild 5", "Tavern", "Shipyard", "Fort", "Citadel", "Castle",
    "Village Hall", "Town Hall", "City Hall", "Capitol", "Marketplace",
    "Resource Silo", "Blacksmith", "Special 1", "Horde 1", "Horde 1 upgrade",
    "Ship", "Special 2", "Special 3", "Special 4", "Horde 2",
    "Horde 2 upgrade", "Grail structure", "Extra Town Hall", "Extra City Hall",
    "Extra Capitol", "Dwelling 1", "Dwelling 2", "Dwelling 3", "Dwelling 4",
    "Dwelling 5", "Dwelling 6", "Dwelling 7", "Dwelling 1 upg",
    "Dwelling 2 upg", "Dwelling 3 upg", "Dwelling 4 upg", "Dwelling 5 upg",
    "Dwelling 6 upg", "Dwelling 7 upg",
]


def bname(i):
    return BUILDINGS[i] if 0 <= i < len(BUILDINGS) else f"Building#{i}"


# --------------------------------------------------------------------------
# Byte reader
# --------------------------------------------------------------------------
class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def i8(self):
        v = struct.unpack_from("<b", self.d, self.p)[0]; self.p += 1; return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]; self.p += 2; return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]; self.p += 4; return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]; self.p += 4; return v

    def bool(self):
        return self.u8() != 0

    def string(self):
        n = self.u32()
        if n > 100000:
            raise ValueError(f"implausible string length {n} at offset {self.p-4}")
        s = self.d[self.p:self.p + n]; self.p += n
        return s.decode("cp1252", errors="replace")

    def skip(self, n):
        self.p += n

    def bits(self, nbytes):
        """Read nbytes as a little-endian bitmask -> list of set bit indices."""
        out = []
        for i in range(nbytes):
            b = self.u8()
            for bit in range(8):
                if b & (1 << bit):
                    out.append(i * 8 + bit)
        return out

    @property
    def left(self):
        return len(self.d) - self.p


# --------------------------------------------------------------------------
# Helpers that depend on map version
# --------------------------------------------------------------------------
class H3MParser:
    def __init__(self, data):
        self.r = Reader(data)
        self.version = None

    # ------------------------------------------------------------------
    # Field tracking, so edits can be written back to the exact bytes.
    #
    # The h3m format holds no internal offset table: nothing anywhere in the
    # file points at a byte position further along. That means a length-
    # prefixed string can be replaced with a longer or shorter one and every
    # following field simply shifts, which is why editing works by splicing
    # recorded byte ranges rather than re-serialising the whole map.
    # ------------------------------------------------------------------
    def tstr(self, target, key):
        off = self.r.p
        v = self.r.string()
        target.setdefault("_off", {})[key] = ("string", off, self.r.p)
        return v

    def tnum(self, target, key, kind):
        off = self.r.p
        v = {"u8": self.r.u8, "u16": self.r.u16, "u32": self.r.u32,
             "i32": self.r.i32, "i8": self.r.i8}[kind]()
        target.setdefault("_off", {})[key] = (kind, off, self.r.p)
        return v

    # feature flags
    @property
    def ab(self):   # Armageddon's Blade or later
        return self.version >= AB

    @property
    def sod(self):  # Shadow of Death or later
        return self.version >= SOD

    def art_id(self):
        """Artifact ids are 1 byte in RoE, 2 bytes afterwards. 0xFF/0xFFFF = none."""
        v = self.r.u8() if not self.ab else self.r.u16()
        none = 0xFF if not self.ab else 0xFFFF
        return None if v == none else v

    def creature_id(self):
        v = self.r.u8() if not self.ab else self.r.u16()
        none = 0xFF if not self.ab else 0xFFFF
        return None if v == none else v

    def creature_set(self, slots=7):
        """Army slots: (creature id, count). Offsets are kept so the creature
        and the amount in any stack — guards, garrisons, hero armies, event
        and Pandora rewards — can be edited in place."""
        out = []
        kind = "u8" if not self.ab else "u16"
        for i in range(slots):
            id_at = self.r.p
            cid = self.creature_id()
            cnt_at = self.r.p
            cnt = self.r.u16()
            rec = {"slot": i, "creature_id": cid, "creature": cname(cid),
                   "count": cnt,
                   "_off": {"creature_id": (kind, id_at, cnt_at),
                            "count": ("u16", cnt_at, self.r.p)}}
            if cid is not None:
                out.append(rec)
        return out

    def resources(self):
        return {RESOURCES[i]: self.r.i32() for i in range(7)}

    # ------------------------------------------------------------------
    def parse(self):
        r = self.r
        self.version = r.u32()
        if self.version not in (ROE, AB, SOD):
            raise ValueError(
                f"Unsupported map version 0x{self.version:02X} "
                f"({VERSION_NAMES.get(self.version, 'unknown')}). "
                "Only RoE / AB / SoD are supported.")

        m = {}
        m["version"] = self.version
        m["version_name"] = VERSION_NAMES[self.version]
        m["any_players"] = r.bool()
        size = r.u32()
        m["size"] = size
        m["has_underground"] = r.bool()
        m["levels"] = 2 if m["has_underground"] else 1
        m["name"] = self.tstr(m, "name")
        m["description"] = self.tstr(m, "description")
        d = r.u8()
        m["difficulty"] = DIFFICULTY[d] if d < len(DIFFICULTY) else d
        m["max_hero_level"] = r.u8() if self.ab else 0

        m["players"] = [self.read_player(i) for i in range(8)]
        m["victory_condition"] = self.read_victory()
        m["loss_condition"] = self.read_loss()

        teams = r.u8()
        m["team_count"] = teams
        m["teams"] = [r.u8() for _ in range(8)] if teams > 0 else []

        # allowed heroes bitmask
        n = 16 if not self.ab else 20
        m["allowed_heroes"] = r.bits(n)
        if self.ab:
            cnt = r.u32()          # "placeholder" heroes
            m["placeholder_heroes"] = [r.u8() for _ in range(cnt)]

        if self.sod:
            m["disposed_heroes"] = []
            for _ in range(r.u8()):
                h = {"hero_id": r.u8(), "portrait": r.u8(), "name": r.string()}
                h["players"] = bit_players(r.u8())
                m["disposed_heroes"].append(h)

        r.skip(31)  # reserved / null

        m["allowed_artifacts"] = r.bits(17 if self.version == AB else 18) if self.ab else []
        m["allowed_spells"] = r.bits(9) if self.sod else []
        m["allowed_skills"] = r.bits(4) if self.sod else []

        rumor_count = r.u32()
        m["rumors"] = []
        for _ in range(rumor_count):
            rec = {}
            rec["name"] = self.tstr(rec, "name")
            rec["text"] = self.tstr(rec, "text")
            m["rumors"].append(rec)

        m["hero_settings"] = self.read_hero_settings() if self.sod else []

        m["terrain"] = self.read_terrain(size, m["levels"])
        m["templates"] = self.read_templates()
        m["objects"] = self.read_objects(m["templates"])
        m.setdefault("_off", {})["object_count"] = self.object_count_off
        m["global_events"] = self.read_events()

        r.skip(124)  # trailing nulls
        m["_bytes_left"] = r.left
        m["_trailing_nonzero"] = any(b != 0 for b in r.d[r.p:])
        return m

    # ------------------------------------------------------------------
    def read_player(self, idx):
        r = self.r
        p = {"index": idx, "color": PLAYERS[idx]}
        p["can_be_human"] = r.bool()
        p["can_be_computer"] = r.bool()
        t = r.u8()
        p["ai_tactic"] = AI_TACTIC[t] if t < len(AI_TACTIC) else t
        if self.sod:
            r.u8()  # allowed-factions customised flag
        mask = r.u16() if self.ab else r.u8()
        p["allowed_factions"] = [FACTIONS[i] for i in range(len(FACTIONS))
                                 if mask & (1 << i)]
        p["is_faction_random"] = r.bool()
        p["has_main_town"] = r.bool()
        if p["has_main_town"]:
            if self.ab:
                p["generate_hero_at_main_town"] = r.bool()
                r.u8()  # unused
            p["main_town"] = self.pos()
        p["has_random_hero"] = r.bool()
        hid = r.u8()
        if hid != 0xFF:
            p["main_hero"] = {"hero_id": hid, "portrait": r.u8(),
                              "name": r.string()}
        if self.ab:
            r.u8()                    # unknown
            cnt = r.u8()
            r.skip(3)
            p["heroes"] = [{"hero_id": r.u8(), "name": r.string()}
                           for _ in range(cnt)]
        return p

    def pos(self):
        r = self.r
        return {"x": r.u8(), "y": r.u8(), "z": r.u8()}

    # ------------------------------------------------------------------
    def read_victory(self):
        r = self.r
        c = r.u8()
        v = {"type": c, "name": VICTORY_CONDITIONS.get(c, f"Unknown({c})")}
        if c == 0xFF:
            return v
        v["allow_normal_victory"] = r.bool()
        v["applies_to_computer"] = r.bool()
        if c == 0:                      # acquire artifact
            v["artifact_id"] = self.art_id() if self.ab else r.u8()
        elif c == 1:                    # accumulate creatures
            v["creature_id"] = self.creature_id()
            v["amount"] = r.u32()
        elif c == 2:                    # accumulate resources
            v["resource"] = RESOURCES[r.u8()]
            v["amount"] = r.u32()
        elif c == 3:                    # upgrade town
            v["town"] = self.pos()
            v["hall_level"] = r.u8()
            v["castle_level"] = r.u8()
        elif c in (4, 5, 6, 7):         # grail / defeat hero / capture town / kill monster
            v["position"] = self.pos()
        elif c in (8, 9):               # flag dwellings / mines
            pass
        elif c == 10:                   # transport artifact
            v["artifact_id"] = r.u8()
            v["position"] = self.pos()
        return v

    def read_loss(self):
        r = self.r
        c = r.u8()
        l = {"type": c, "name": LOSS_CONDITIONS.get(c, f"Unknown({c})")}
        if c in (0, 1):
            l["position"] = self.pos()
        elif c == 2:
            l["days"] = r.u16()
        return l

    # ------------------------------------------------------------------
    def read_hero_settings(self):
        r = self.r
        out = []
        for hid in range(156):
            if not r.bool():
                continue
            h = {"hero_id": hid}
            if r.bool():
                h["experience"] = r.u32()
            if r.bool():
                h["secondary_skills"] = [
                    {"skill": sname(r.u8()), "level": SEC_LEVELS[r.u8()]}
                    for _ in range(r.u32())]
            if r.bool():
                h["artifacts"] = self.read_hero_artifacts()
            if r.bool():
                h["biography"] = r.string()
            h["sex"] = {0: "Male", 1: "Female", 255: "Default"}.get(r.u8(), "?")
            if r.bool():
                h["spells"] = r.bits(9)
            if r.bool():
                h["primary_skills"] = {PRIMARY_SKILLS[i]: r.u8() for i in range(4)}
            out.append(h)
        return out

    def read_hero_artifacts(self):
        r = self.r
        arts = {}
        slots = 16                      # head..misc4 + so on
        for i in range(slots):
            a = self.art_id()
            if a is not None:
                arts[f"slot{i}"] = {"id": a}
        if self.sod:
            a = self.art_id()           # misc5
            if a is not None:
                arts["misc5"] = {"id": a}
        a = self.art_id()               # spellbook
        if a is not None:
            arts["spellbook"] = {"id": a}
        if self.ab:
            a = self.art_id()           # war machine 4 (ballista cart slot)
            if a is not None:
                arts["machine4"] = {"id": a}
        else:
            r.skip(1)
        backpack = []
        for _ in range(r.u16()):
            a = self.art_id()
            if a is not None:
                backpack.append(a)
        if backpack:
            arts["backpack"] = backpack
        return arts

    # ------------------------------------------------------------------
    def read_terrain(self, size, levels):
        r = self.r
        tiles = []
        for z in range(levels):
            for y in range(size):
                for x in range(size):
                    t = r.u8(); tv = r.u8()
                    rv = r.u8(); rd = r.u8()
                    rt = r.u8(); rdd = r.u8()
                    flags = r.u8()
                    tiles.append((x, y, z, t, tv, rv, rd, rt, rdd, flags))
        return tiles

    # ------------------------------------------------------------------
    def read_templates(self):
        r = self.r
        out = []
        for i in range(r.u32()):
            t = {"index": i, "def": r.string()}
            t["block_mask"] = [r.u8() for _ in range(6)]
            t["visit_mask"] = [r.u8() for _ in range(6)]
            r.u16()                       # allowed terrains
            r.u16()                       # terrain group
            t["object_id"] = r.u32()
            t["object_subid"] = r.u32()
            t["object_group"] = r.u8()    # 0=terrain,1=town,2=monster,3=hero,4=artifact,5=treasure
            t["print_priority"] = r.u8()
            r.skip(16)
            t["name"] = OBJECTS.get(t["object_id"], f"Unknown({t['object_id']})")
            out.append(t)
        return out

    # ------------------------------------------------------------------
    def read_objects(self, templates):
        r = self.r
        count_at = r.p
        n = r.u32()
        self.object_count_off = ("u32", count_at, r.p)
        out = []
        for i in range(n):
            obj_start = r.p
            x, y, z = r.u8(), r.u8(), r.u8()
            ti = r.u32()
            r.skip(5)
            if ti >= len(templates):
                raise ValueError(f"object {i}: template index {ti} out of range "
                                 f"at offset {r.p}")
            tpl = templates[ti]
            oid, sub = tpl["object_id"], tpl["object_subid"]
            o = {"index": i, "x": x, "y": y, "z": z,
                 "object_id": oid, "object_subid": sub,
                 "name": OBJECTS.get(oid, f"Unknown({oid})"),
                 "def": tpl["def"], "template_index": ti}
            try:
                self.read_object_body(o, oid, sub)
            except (IndexError, struct.error) as e:
                raise ValueError(f"object {i} ({o['name']}) at "
                                 f"({x},{y},{z}): {e}") from e
            o["_span"] = (obj_start, r.p)     # whole record, for deletion
            out.append(o)
        return out

    def read_object_body(self, o, oid, sub):
        r = self.r
        if oid in (34, 70, 62):                       # Hero / Random hero / Prison
            o.update(self.read_hero(oid, sub))
        elif oid in (98, 77):                         # Town / Random town
            o.update(self.read_town(sub))
        elif oid in (54, 71, 72, 73, 74, 75, 162, 163, 164):   # Monsters
            o.update(self.read_monster())
        elif oid in (5, 65, 66, 67, 68, 69, 93):      # Artifacts / spell scroll
            o.update(self.read_message_and_guards())
            if oid == 93:
                sid = r.u32()
                o["spell_id"] = sid
        elif oid in (76, 79):                         # Resource
            o.update(self.read_message_and_guards())
            o["amount"] = self.tnum(o, "amount", "u32")
            r.skip(4)
        elif oid in (33, 219):                        # Garrison
            o["owner"] = player_name(self.tnum(o, "owner", "u32"))
            o["army"] = self.creature_set()
            o["removable_units"] = r.bool() if self.ab else True
            r.skip(8)
        elif oid in (91, 59):                         # Sign / Ocean bottle
            o["message"] = self.tstr(o, "message")
            r.skip(4)
        elif oid == 83:                               # Seer's Hut
            o.update(self.read_seer_hut())
        elif oid == 215:                              # Quest Guard
            o["quest"] = self.read_quest()
        elif oid == 113:                              # Witch Hut
            if self.ab:
                o["allowed_skills"] = [sname(i) for i in r.bits(4)]
        elif oid == 81:                               # Scholar
            bt = r.u8(); bid = r.u8()
            o["bonus_type"] = {0: "Primary skill", 1: "Secondary skill",
                               2: "Spell", 255: "Random"}.get(bt, bt)
            o["bonus_id"] = bid
            r.skip(6)
        elif oid in (88, 89, 90):                     # Shrines
            o["spell_id"] = r.u32()
        elif oid == 6:                                # Pandora's Box
            o.update(self.read_reward_bundle())
        elif oid == 26:                               # Event
            o.update(self.read_reward_bundle())
            o["available_for"] = bit_players(r.u8())
            o["computer_activate"] = r.bool()
            o["remove_after_visit"] = r.bool()
            r.skip(4)
        elif oid == 36:                               # Grail
            o["radius"] = r.u32()
        elif oid in (17, 20, 42, 87):                 # Dwelling / lighthouse / shipyard
            o["owner"] = player_name(self.tnum(o, "owner", "u32"))
        elif oid == 53:                               # Mine
            o["mine_type"] = MINE_SUBTYPE.get(sub, sub)
            if sub < 7:
                o["owner"] = player_name(self.tnum(o, "owner", "u32"))
            else:
                o["resources"] = [RESOURCES[i] for i in r.bits(4)
                                  if i < len(RESOURCES)]
        elif oid == 220:                              # Abandoned mine
            o["resources"] = [RESOURCES[i] for i in r.bits(4)
                              if i < len(RESOURCES)]
        elif oid == 216:                              # Random dwelling
            o["owner"] = player_name(r.u32())
            ident = r.u32()
            if ident == 0:
                mask = r.u16()
                o["factions"] = [FACTIONS[i] for i in range(9) if mask & (1 << i)]
            o["min_level"], o["max_level"] = r.u8(), r.u8()
        elif oid == 217:                              # Random dwelling, fixed level
            o["owner"] = player_name(r.u32())
            ident = r.u32()
            if ident == 0:
                mask = r.u16()
                o["factions"] = [FACTIONS[i] for i in range(9) if mask & (1 << i)]
        elif oid == 218:                              # Random dwelling, fixed faction
            o["owner"] = player_name(r.u32())
            o["min_level"], o["max_level"] = r.u8(), r.u8()
        elif oid == 214:                              # Hero placeholder
            o["owner"] = player_name(r.u8())
            hid = r.u8()
            if hid == 0xFF:
                o["power_rank"] = r.u8()
            else:
                o["hero_id"] = hid
        elif oid in (9, 10, 212):                     # Border guard / keymaster / gate
            o["tent_colour"] = sub
        # everything else has no extra body

    # ------------------------------------------------------------------
    def read_hero(self, oid, sub):
        r = self.r
        h = {}
        if self.ab:
            h["identifier"] = r.u32()
        h["owner"] = player_name(self.tnum(h, "owner", "u8"))
        h["hero_id"] = self.tnum(h, "hero_id", "u8")
        if r.bool():
            h["hero_name"] = self.tstr(h, "hero_name")
        if self.sod:
            if r.bool():
                h["experience"] = r.u32()
        else:
            h["experience"] = r.u32()
        if r.bool():
            h["portrait"] = r.u8()
        if r.bool():
            h["secondary_skills"] = [
                {"skill": sname(r.u8()), "level": SEC_LEVELS[r.u8()]}
                for _ in range(r.u32())]
        if r.bool():
            h["army"] = self.creature_set()
        h["formation"] = FORMATION[r.u8() & 1]
        if r.bool():
            h["artifacts"] = self.read_hero_artifacts()
        h["patrol_radius"] = r.u8()
        if self.ab:
            if r.bool():
                h["biography"] = r.string()
            h["sex"] = {0: "Male", 1: "Female", 255: "Default"}.get(r.u8(), "?")
        if self.sod:
            if r.bool():
                h["spells"] = r.bits(9)
        elif self.ab:
            h["spell"] = r.u8()
        if self.sod:
            if r.bool():
                h["primary_skills"] = {PRIMARY_SKILLS[i]: r.u8() for i in range(4)}
        r.skip(16)
        return h

    def read_town(self, sub):
        r = self.r
        t = {"faction": FACTIONS[sub] if sub < len(FACTIONS) else sub}
        if self.ab:
            t["identifier"] = r.u32()
        t["owner"] = player_name(self.tnum(t, "owner", "u8"))
        if r.bool():
            t["town_name"] = self.tstr(t, "town_name")
        if r.bool():
            t["army"] = self.creature_set()
        t["formation"] = FORMATION[r.u8() & 1]
        if r.bool():
            t["buildings_built"] = r.bits(6)
            t["buildings_forbidden"] = r.bits(6)
        else:
            t["has_fort"] = r.bool()
        if self.ab:
            t["spells_obligatory"] = r.bits(9)
        t["spells_possible"] = r.bits(9)
        t["events"] = [self.read_event(town=True) for _ in range(r.u32())]
        if self.sod:
            a = r.i8()
            t["alignment"] = "Same as owner" if a == 255 else a
        r.skip(3)
        return t

    def read_monster(self):
        r = self.r
        m = {}
        if self.ab:
            m["identifier"] = r.u32()
        m["count"] = self.tnum(m, "count", "u16")
        c = self.tnum(m, "disposition", "u8")
        m["disposition"] = MONSTER_CHARACTER.get(c, c)
        if r.bool():
            m["message"] = self.tstr(m, "message")
            m["reward_resources"] = self.resources()
            m["reward_artifact"] = self.art_id()
        m["never_flees"] = bool(self.tnum(m, "never_flees", "u8"))
        m["does_not_grow"] = bool(self.tnum(m, "does_not_grow", "u8"))
        r.skip(2)
        return m

    def read_message_and_guards(self):
        r = self.r
        d = {}
        if r.bool():
            d["message"] = self.tstr(d, "message")
            if r.bool():
                d["guards"] = self.creature_set()
            r.skip(4)
        return d

    def read_reward_bundle(self):
        """Shared body of Pandora's Box and Event."""
        r = self.r
        d = self.read_message_and_guards()
        d["experience"] = r.u32()
        d["spell_points"] = r.i32()
        d["morale"] = r.i8()
        d["luck"] = r.i8()
        d["resources"] = self.resources()
        d["primary_skills"] = {PRIMARY_SKILLS[i]: r.u8() for i in range(4)}
        d["secondary_skills"] = [
            {"skill": sname(r.u8()), "level": SEC_LEVELS[r.u8()]}
            for _ in range(r.u8())]
        d["artifacts"] = [self.art_id() for _ in range(r.u8())]
        d["spells"] = [r.u8() for _ in range(r.u8())]
        d["creatures"] = self.creature_set(r.u8())
        r.skip(8)
        return {k: v for k, v in d.items() if v not in (0, [], {}, None)}

    def read_quest(self):
        r = self.r
        t = r.u8()
        q = {"mission_type": t, "mission": QUEST_MISSIONS.get(t, t)}
        if t == 0:
            return q
        if t == 1:
            q["level"] = r.u32()
        elif t == 2:
            q["primary_skills"] = {PRIMARY_SKILLS[i]: r.u8() for i in range(4)}
        elif t == 3:
            q["hero_identifier"] = r.u32()
        elif t == 4:
            q["monster_identifier"] = r.u32()
        elif t == 5:
            q["artifacts"] = [self.art_id() for _ in range(r.u8())]
        elif t == 6:
            q["creatures"] = [{"creature": cname(self.creature_id()),
                               "count": r.u16()} for _ in range(r.u8())]
        elif t == 7:
            q["resources"] = self.resources()
        elif t == 8:
            q["hero_id"] = r.u8()
        elif t == 9:
            q["player"] = player_name(r.u8())
        q["deadline"] = r.u32()
        q["first_visit_text"] = self.tstr(q, "first_visit_text")
        q["next_visit_text"] = self.tstr(q, "next_visit_text")
        q["completed_text"] = self.tstr(q, "completed_text")
        return q

    def read_seer_hut(self):
        r = self.r
        d = {}
        if self.ab:
            q = self.read_quest()
        else:
            a = r.u8()
            q = {"mission_type": 5 if a != 255 else 0,
                 "mission": "Bring artifacts" if a != 255 else "None"}
            if a != 255:
                q["artifacts"] = [a]
                q["deadline"] = r.u32()
                q["first_visit_text"] = r.string()
                q["next_visit_text"] = r.string()
                q["completed_text"] = r.string()
        d["quest"] = q
        if q["mission_type"] != 0:
            rt = r.u8()
            rw = {"type": rt, "reward": SEER_REWARDS.get(rt, rt)}
            if rt == 1 or rt == 2:
                rw["amount"] = r.u32()
            elif rt in (3, 4):
                rw["amount"] = r.u8()
            elif rt == 5:
                rw["resource"] = RESOURCES[r.u8() & 7]
                rw["amount"] = r.u32() & 0x00FFFFFF
            elif rt == 6:
                rw["skill"] = PRIMARY_SKILLS[r.u8() & 3]; rw["amount"] = r.u8()
            elif rt == 7:
                rw["skill"] = sname(r.u8()); rw["level"] = SEC_LEVELS[r.u8()]
            elif rt == 8:
                rw["artifact_id"] = self.art_id()
            elif rt == 9:
                rw["spell_id"] = r.u8()
            elif rt == 10:
                rw["creature_id"] = self.creature_id()
                rw["count"] = r.u16()
            d["reward"] = rw
            r.skip(2)
        else:
            r.skip(3)
        return d

    def read_event(self, town=False):
        r = self.r
        e = {}
        e["name"] = self.tstr(e, "name")
        e["message"] = self.tstr(e, "message")
        e["resources"] = self.resources()
        e["players"] = bit_players(r.u8())
        if self.sod:
            e["human_affected"] = r.bool()
        e["computer_affected"] = r.bool()
        e["first_occurrence"] = r.u16()
        e["repeat_after"] = r.u8()
        r.skip(17)
        if town:
            e["buildings"] = r.bits(6)
            e["creatures"] = [r.u16() for _ in range(7)]
            r.skip(4)
        return e

    def read_events(self):
        return [self.read_event() for _ in range(self.r.u32())]


# --------------------------------------------------------------------------
def cname(i):
    if i is None:
        return None
    return CREATURES[i] if 0 <= i < len(CREATURES) else f"Creature#{i}"

def sname(i):
    return SEC_SKILLS[i] if 0 <= i < len(SEC_SKILLS) else f"Skill#{i}"

def bit_players(mask):
    return [PLAYERS[i] for i in range(8) if mask & (1 << i)]


def parse_bytes(data):
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    m = H3MParser(data).parse()
    m["_raw"] = data          # needed to write edits back
    m["_edits"] = []
    m["_deleted"] = []
    return m


def parse_file(path):
    with open(path, "rb") as f:
        return parse_bytes(f.read())




# --------------------------------------------------------------------------
# Editing and writing maps back out
# --------------------------------------------------------------------------
# Nothing in an h3m file refers to a byte position elsewhere in the file, so
# an edit can be applied by replacing the exact byte range a field occupied.
# Strings may change length: everything after simply shifts. This is why the
# writer patches recorded ranges instead of re-serialising the map, which
# would risk corrupting the many fields the parser skips over verbatim.

class EditError(Exception):
    pass


def editable_fields(target):
    """Field names on a parsed map or object that can be edited."""
    return sorted((target.get("_off") or {}).keys())


def _encode(kind, value):
    if kind == "string":
        if not isinstance(value, str):
            raise EditError(f"expected text, got {type(value).__name__}")
        b = value.encode("cp1252", errors="replace")
        return struct.pack("<I", len(b)) + b
    if kind == "u8":
        v = int(value)
        if not 0 <= v <= 0xFF:
            raise EditError(f"{v} does not fit in one byte")
        return struct.pack("<B", v)
    if kind == "i8":
        return struct.pack("<b", int(value))
    if kind == "u16":
        v = int(value)
        if not 0 <= v <= 0xFFFF:
            raise EditError(f"{v} does not fit in two bytes (max 65535)")
        return struct.pack("<H", v)
    if kind == "u32":
        v = int(value)
        if not 0 <= v <= 0xFFFFFFFF:
            raise EditError(f"{v} does not fit in four bytes")
        return struct.pack("<I", v)
    if kind == "i32":
        return struct.pack("<i", int(value))
    raise EditError(f"unknown field kind {kind}")


# Some fields are parsed into readable labels rather than raw numbers, so an
# edit has to accept the label the user actually sees.
BOOL_WORDS = {"yes": 1, "no": 0, "true": 1, "false": 0, "on": 1, "off": 0}


def field_choices(key):
    """Allowed values for a field that is not a free number, else None."""
    if key == "owner":
        return PLAYERS + ["Neutral/None"]
    if key == "disposition":
        return [MONSTER_CHARACTER[i] for i in sorted(MONSTER_CHARACTER)]
    if key in ("never_flees", "does_not_grow"):
        return ["No", "Yes"]
    if key == "creature_id":
        return [n for n in CREATURES if "NOT USED" not in n]
    return None


def _coerce(key, value):
    """Turn a displayed label back into the number stored in the file."""
    if key == "owner":
        return _owner_to_index(value)
    if key == "disposition":
        if isinstance(value, str):
            for num, name in MONSTER_CHARACTER.items():
                if name.lower() == value.strip().lower():
                    return num
            raise EditError(
                f"unknown disposition {value!r}; expected one of "
                + ", ".join(field_choices("disposition")))
        return int(value)
    if key == "creature_id":
        if isinstance(value, str):
            want = value.strip().lower()
            for i, n in enumerate(CREATURES):
                if n.lower() == want:
                    return i
            raise EditError(f"unknown creature {value!r}")
        return int(value)
    if key in ("never_flees", "does_not_grow"):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in BOOL_WORDS:
                return BOOL_WORDS[v]
        return int(value)
    return value


def edit(m, target, key, value, label=None):
    """Queue a change to one field. Nothing is written until save()."""
    off = (target.get("_off") or {}).get(key)
    if off is None:
        raise EditError(
            f"'{key}' is not an editable field here. Available: "
            + (", ".join(editable_fields(target)) or "none"))
    kind, start, end = off
    if kind != "string":
        value = _coerce(key, value)
    payload = _encode(kind, value)
    m.setdefault("_edits", []).append(
        {"offset": start, "end": end, "bytes": payload, "kind": kind,
         "key": key, "value": value,
         "label": label or f"{key} @ {start}"})
    return m["_edits"][-1]


def _owner_to_index(value):
    if isinstance(value, int):
        return value
    if value in (None, "", "Neutral", "Neutral/None", "None"):
        return 255
    try:
        return PLAYERS.index(value)
    except ValueError:
        raise EditError(f"unknown player {value!r}")




def delete_object(m, o):
    """Queue removal of a whole object. Nothing is written until save()."""
    if "_span" not in o:
        raise EditError("this object cannot be removed (no recorded extent)")
    if o["index"] in m.get("_deleted", []):
        return
    m.setdefault("_deleted", []).append(o["index"])
    # a field edit on a removed object would overlap the removal
    m["_edits"] = [e for e in m.get("_edits", [])
                   if not (o["_span"][0] <= e["offset"] < o["_span"][1])]


def undelete_object(m, o):
    if o["index"] in m.get("_deleted", []):
        m["_deleted"].remove(o["index"])


def deleted_objects(m):
    return [m["objects"][i] for i in m.get("_deleted", [])]


def _deletion_edits(m):
    """Turn queued deletions into byte splices plus one object-count update."""
    dels = m.get("_deleted") or []
    if not dels:
        return []
    edits = []
    for idx in dels:
        o = m["objects"][idx]
        start, end = o["_span"]
        edits.append({"offset": start, "end": end, "bytes": b"",
                      "kind": "delete", "key": "object",
                      "value": None,
                      "label": f"remove {o['name']} at "
                               f"({o['x']},{o['y']},{o['z']})"})
    kind, start, end = m["_off"]["object_count"]
    edits.append({"offset": start, "end": end,
                  "bytes": struct.pack("<I", len(m["objects"]) - len(dels)),
                  "kind": kind, "key": "object_count", "value": None,
                  "label": f"object count -{len(dels)}"})
    return edits


def pending_edits(m):
    """Every queued change, field edits and deletions alike."""
    return list(m.get("_edits") or []) + _deletion_edits(m)


def revert_edit(m, entry):
    """Undo one queued change before saving."""
    if entry.get("kind") == "delete":
        for idx in list(m.get("_deleted", [])):
            o = m["objects"][idx]
            if o["_span"][0] == entry["offset"]:
                m["_deleted"].remove(idx)
                return True
        return False
    for e in list(m.get("_edits", [])):
        if e["offset"] == entry["offset"] and e["key"] == entry["key"]:
            m["_edits"].remove(e)
            return True
    return False


def clear_edits(m):
    m["_edits"] = []
    m["_deleted"] = []


def apply_edits(raw, edits):
    """Splice queued edits into the decompressed bytes."""
    if not edits:
        return raw
    ordered = sorted(edits, key=lambda e: e["offset"])
    for a, b in zip(ordered, ordered[1:]):
        if b["offset"] < a["end"]:
            raise EditError(
                f"two edits overlap at byte {b['offset']} "
                f"({a['label']} and {b['label']})")
    out = bytearray(raw)
    for e in reversed(ordered):        # back to front keeps offsets valid
        out[e["offset"]:e["end"]] = e["bytes"]
    return bytes(out)


def save(m, path, verify=True):
    """Write the map, with any queued edits applied, as a gzipped .h3m.

    By default the result is re-parsed before being written, so a change that
    would corrupt the file is caught here rather than by the game.
    """
    raw = m.get("_raw")
    if raw is None:
        raise EditError("this map was not loaded with its raw bytes")
    data = apply_edits(raw, pending_edits(m))
    expected_objects = len(m["objects"]) - len(m.get("_deleted") or [])

    if verify:
        try:
            check = H3MParser(data).parse()
        except Exception as exc:
            raise EditError(f"the edited map does not parse: {exc}") from exc
        if check["_bytes_left"] != 0:
            raise EditError(
                f"the edited map left {check['_bytes_left']} trailing bytes; "
                "refusing to write a file that may be corrupt")
        if len(check["objects"]) != expected_objects:
            raise EditError(
                f"expected {expected_objects} objects after editing but the "
                f"result has {len(check['objects'])}; refusing to write")

    with open(path, "wb") as f:
        f.write(gzip_h3m(data))
    return path


def gzip_h3m(data, level=9):
    """Compress to the exact gzip shape Heroes 3 map files use.

    This is built by hand rather than with gzip.GzipFile because that helper
    writes the output filename into the gzip header (the FNAME flag). Heroes 3
    reads the header as a fixed ten bytes and does not skip FNAME, so a file
    written that way is read with the filename as its first bytes of map data
    and will not open in the game or the map editor. Real .h3m files carry a
    bare header: no flags, no timestamp, OS byte 11.
    """
    body = zlib.compress(data, level)[2:-4]        # strip zlib wrapper
    return (b"\x1f\x8b\x08\x00"                  # magic, deflate, no flags
            + b"\x00\x00\x00\x00"                 # mtime 0
            + b"\x00\x0b"                          # XFL 0, OS 11 (NTFS)
            + body
            + struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)
            + struct.pack("<I", len(data) & 0xFFFFFFFF))


# --------------------------------------------------------------------------
# Round-trip text editing
# --------------------------------------------------------------------------
def _text_targets(m):
    """(id, where, target dict, key) for every editable piece of text."""
    out = [("map.name", "Map name", m, "name"),
           ("map.description", "Map description", m, "description")]
    for i, r in enumerate(m["rumors"]):
        out.append((f"rumor{i}.name", f"Rumor {i + 1} name", r, "name"))
        out.append((f"rumor{i}.text", f"Rumor {i + 1} text", r, "text"))
    for i, e in enumerate(m["global_events"]):
        out.append((f"event{i}.name", f"Timed event {i + 1} name", e, "name"))
        out.append((f"event{i}.message", f"Timed event {i + 1} text", e, "message"))
    for o in m["objects"]:
        where = f"{o['name']} at ({o['x']},{o['y']},{o['z']})"
        for key in ("message", "hero_name", "town_name"):
            if key in (o.get("_off") or {}):
                out.append((f"obj{o['index']}.{key}", f"{where} — {key}", o, key))
        q = o.get("quest") or {}
        for key in ("first_visit_text", "next_visit_text", "completed_text"):
            if key in (q.get("_off") or {}):
                out.append((f"obj{o['index']}.quest.{key}", f"{where} — {key}",
                            q, key))
        for j, ev in enumerate(o.get("events") or []):
            for key in ("name", "message"):
                if key in (ev.get("_off") or {}):
                    out.append((f"obj{o['index']}.event{j}.{key}",
                                f"{where} — town event {j + 1} {key}", ev, key))
    return out


def text_location(m, text_id):
    """Where a text entry sits on the map, or None if it has no position.

    Map name, description, rumors and timed events belong to the map as a
    whole; everything else is attached to an object whose index the id
    carries.
    """
    if not text_id or not text_id.startswith("obj"):
        return None
    head = text_id.split(".", 1)[0]
    try:
        index = int(head[3:])
    except ValueError:
        return None
    if not 0 <= index < len(m["objects"]):
        return None
    o = m["objects"][index]
    return {"index": index, "x": o["x"], "y": o["y"], "z": o["z"],
            "name": o["name"]}


def export_texts(m, path):
    """Write every editable string to a JSON file for editing."""
    doc = {"_map": m["name"], "_note":
           "Edit the 'text' values only. Leave 'id' alone. Import with "
           "import_texts() or the GUI to apply.",
           "texts": [{"id": tid, "where": where, "text": target[key]}
                     for tid, where, target, key in _text_targets(m)]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    return path


def import_texts(m, path):
    """Apply an edited text file. Returns the list of changes queued."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    index = {tid: (where, target, key)
             for tid, where, target, key in _text_targets(m)}
    changed = []
    for entry in doc.get("texts", []):
        tid, new = entry.get("id"), entry.get("text")
        if tid not in index:
            continue
        where, target, key = index[tid]
        if new is None or new == target[key]:
            continue
        edit(m, target, key, new, label=where)
        changed.append({"id": tid, "where": where,
                        "old": target[key], "new": new})
    return changed


# --------------------------------------------------------------------------
# CLI output
# --------------------------------------------------------------------------
def summarise(m, path):
    L = []
    a = L.append
    a(f"File          : {os.path.basename(path)}")
    a(f"Format        : {m['version_name']} (0x{m['version']:02X})")
    a(f"Name          : {m['name'] or '(untitled)'}")
    a(f"Size          : {m['size']}x{m['size']}"
      f"{' + underground' if m['has_underground'] else ' (surface only)'}")
    a(f"Difficulty    : {m['difficulty']}")
    a(f"Max hero level: {m['max_hero_level'] or 'unlimited'}")
    a(f"Victory       : {m['victory_condition']['name']}")
    a(f"Loss          : {m['loss_condition']['name']}")
    a(f"Teams         : {m['team_count'] or 'none'}")
    a("")
    desc = (m["description"] or "").strip()
    if desc:
        a("Description:")
        a("  " + desc.replace("\n", "\n  ")[:1500])
        a("")

    a("Players:")
    for p in m["players"]:
        if not (p["can_be_human"] or p["can_be_computer"]):
            continue
        who = []
        if p["can_be_human"]:
            who.append("human")
        if p["can_be_computer"]:
            who.append("AI")
        mt = p.get("main_town")
        a(f"  {p['color']:<7} {'/'.join(who):<9} "
          f"towns: {','.join(p['allowed_factions']) or '-'}"
          + (f"  main town @ ({mt['x']},{mt['y']},{mt['z']})" if mt else ""))
    a("")

    objs = m["objects"]
    a(f"Objects       : {len(objs)}  (from {len(m['templates'])} templates)")
    counts = Counter(o["name"] for o in objs)
    a("Most common object types:")
    for name, c in counts.most_common(15):
        a(f"  {c:>5}  {name}")
    a("")

    towns = [o for o in objs if o["object_id"] in (98, 77)]
    heroes = [o for o in objs if o["object_id"] in (34, 70, 62)]
    mines = [o for o in objs if o["object_id"] in (53, 220)]
    monsters = [o for o in objs if o["object_id"] in (54, 71, 72, 73, 74, 75,
                                                      162, 163, 164)]
    a(f"Towns: {len(towns)}   Heroes: {len(heroes)}   "
      f"Mines: {len(mines)}   Monster stacks: {len(monsters)}")
    if towns:
        a("")
        a("Towns:")
        for t in towns:
            a(f"  ({t['x']:>3},{t['y']:>3},{t['z']}) {t.get('faction','random'):<11}"
              f" {t.get('owner','?'):<13} {t.get('town_name','')}")
    if heroes:
        a("")
        a("Heroes:")
        for h in heroes:
            a(f"  ({h['x']:>3},{h['y']:>3},{h['z']}) {h['name']:<12}"
              f" {h.get('owner','?'):<13} {h.get('hero_name','')}"
              f" (id {h.get('hero_id','?')})")
    if m["rumors"]:
        a("")
        a(f"Rumors: {len(m['rumors'])}")
    if m["global_events"]:
        a(f"Timed events: {len(m['global_events'])}")
    a("")
    a(f"[parser consumed everything except {m['_bytes_left']} trailing bytes; "
      f"non-zero leftovers: {m['_trailing_nonzero']}]")
    return "\n".join(L)


def objects_table(m):
    rows = []
    for o in m["objects"]:
        rows.append({
            "x": o["x"], "y": o["y"], "z": o["z"],
            "object_id": o["object_id"], "subid": o["object_subid"],
            "type": o["name"], "def": o["def"],
            "owner": o.get("owner", ""),
            "detail": detail_of(o),
        })
    return rows


def detail_of(o):
    oid = o["object_id"]
    sub = o["object_subid"]
    if oid in (98, 77):
        return f"{o.get('faction','random')} {o.get('town_name','')}".strip()
    if oid in (34, 70, 62):
        nm = o.get("hero_name") or hname(o.get("hero_id"))
        return f"{nm} (class hero id {o.get('hero_id','?')})"
    if oid in (54, 71, 72, 73, 74, 75, 162, 163, 164):
        n = cname(sub) if oid == 54 else "random creature"
        c = o.get("count", 0)
        amount = f"{c}x" if c else "random count of"
        return f"{amount} {n} [{o.get('disposition','')}]"
    if oid in (76, 79):
        res = RESOURCES[sub] if sub < 7 else "random resource"
        amt = o.get("amount", 0)
        return f"{amt if amt else 'random amount'} {res}"
    if oid == 53:
        return str(o.get("mine_type", ""))
    if oid == 220:
        return "abandoned: " + ", ".join(o.get("resources", []))
    if oid == 5:
        return aname(sub)
    if oid in (65, 66, 67, 68, 69):
        return "random artifact"
    if oid == 93:
        return f"scroll: {spname(o.get('spell_id'))}"
    if oid in (88, 89, 90):
        return f"teaches {spname(o.get('spell_id'))}"
    if oid in (91, 59):
        return (o.get("message", "") or "")[:100].replace("\n", " ")
    if oid == 83:
        q = o.get("quest", {})
        rw = o.get("reward", {})
        bits = f"{q.get('mission','')} -> {rw.get('reward','')}"
        if rw.get("reward") == "Artifact":
            bits += f" ({aname(rw.get('artifact_id'))})"
        elif rw.get("reward") == "Spell":
            bits += f" ({spname(rw.get('spell_id'))})"
        elif rw.get("reward") == "Creatures":
            bits += f" ({rw.get('count')}x {cname(rw.get('creature_id'))})"
        elif "amount" in rw:
            bits += f" ({rw.get('resource','')} {rw['amount']})".replace("( ", "(")
        return bits
    if oid == 215:
        return f"quest: {o.get('quest',{}).get('mission','')}"
    if oid == 113:
        sk = o.get("allowed_skills", [])
        return "teaches: " + (", ".join(sk) if len(sk) < 6 else f"{len(sk)} skills")
    if oid in (6, 26):
        parts = []
        if o.get("experience"):
            parts.append(f"{o['experience']} exp")
        if o.get("spell_points"):
            parts.append(f"{o['spell_points']} mana")
        res = {k: v for k, v in (o.get("resources") or {}).items() if v}
        parts += [f"{v} {k}" for k, v in res.items()]
        parts += [f"+{v} {k}" for k, v in (o.get("primary_skills") or {}).items() if v]
        parts += [aname(a) for a in (o.get("artifacts") or [])]
        parts += [spname(s) for s in (o.get("spells") or [])]
        parts += [f"{c['count']}x {c['creature']}" for c in (o.get("creatures") or [])]
        if o.get("guards"):
            parts.append("guarded")
        return "; ".join(parts) or "empty"
    if oid in (33, 219):
        return ", ".join(f"{a['count']}x {a['creature']}" for a in o.get("army", []))
    if oid in (17, 18, 19, 20):
        return dwelling_name(oid, sub, o.get("def", "")) or "creature dwelling"
    if oid in (216, 217, 218):
        return "random dwelling"
    if oid in (43, 44, 45, 103, 111):
        return f"portal/gate group {sub}"
    if oid in (9, 10, 212):
        return f"key colour {sub}"
    if oid == 36:
        return f"grail, radius {o.get('radius')}"
    if oid == 8:
        return "boat"
    return ""



# --------------------------------------------------------------------------
# Extra reports
# --------------------------------------------------------------------------

def quest_requirement(q):
    """Readable summary of what a quest asks for."""
    t = q.get("mission_type")
    if t == 1:
        return f"hero level {q.get('level')}"
    if t == 2:
        return ", ".join(f"{k} {v}" for k, v in q.get("primary_skills", {}).items() if v)
    if t == 3:
        return "defeat a specific hero"
    if t == 4:
        return "defeat a specific monster"
    if t == 5:
        return ", ".join(aname(a) for a in q.get("artifacts", []))
    if t == 6:
        return ", ".join(f"{c['count']}x {c['creature']}" for c in q.get("creatures", []))
    if t == 7:
        return ", ".join(f"{v} {k}" for k, v in q.get("resources", {}).items() if v)
    if t == 8:
        return f"be {hname(q.get('hero_id'))}"
    if t == 9:
        return f"be {q.get('player')}"
    return ""


def texts_report(m, path):
    """Every human-authored string in the map, in one document."""
    L = []
    a = L.append
    a(f"# Text dump: {m['name'] or os.path.basename(path)}\n")

    if m["description"].strip():
        a("## Map description\n")
        a(m["description"].strip() + "\n")

    if m["rumors"]:
        a("## Tavern rumors\n")
        for r in m["rumors"]:
            a(f"- **{r['name']}** — {r['text']}")
        a("")

    if m["global_events"]:
        a("## Timed events\n")
        for e in m["global_events"]:
            res = ", ".join(f"{v:+} {k}" for k, v in e["resources"].items() if v)
            a(f"### {e['name']}  (day {e['first_occurrence'] + 1}"
              + (f", repeats every {e['repeat_after']} days" if e["repeat_after"] else "")
              + f", players: {', '.join(e['players']) or 'none'})")
            if res:
                a(f"*Resources: {res}*")
            if e["message"].strip():
                a(e["message"].strip())
            a("")

    def objs(*ids):
        return [o for o in m["objects"] if o["object_id"] in ids]

    signs = [o for o in objs(91, 59) if o.get("message", "").strip()]
    if signs:
        a("## Signs and ocean bottles\n")
        for o in signs:
            a(f"- ({o['x']},{o['y']},{o['z']}) [{o['name']}] {o['message'].strip()}")
        a("")

    seers = objs(83)
    if seers:
        a("## Seer's Huts\n")
        for o in seers:
            q = o.get("quest", {})
            a(f"### ({o['x']},{o['y']},{o['z']}) — {q.get('mission','?')} "
              f"-> {detail_of(o).split('-> ')[-1]}")
            req = quest_requirement(q)
            if req:
                a(f"- *Requires:* {req}")
            for k, label in (("first_visit_text", "On arrival"),
                             ("next_visit_text", "Return visit"),
                             ("completed_text", "On completion")):
                if q.get(k, "").strip():
                    a(f"- *{label}:* {q[k].strip()}")
            a("")

    mons = [o for o in objs(54, 71, 72, 73, 74, 75, 162, 163, 164)
            if o.get("message", "").strip()]
    if mons:
        a("## Monster guard messages\n")
        for o in mons:
            a(f"- ({o['x']},{o['y']},{o['z']}) {detail_of(o)}: {o['message'].strip()}")
        a("")

    boxes = [o for o in objs(6, 26) if o.get("message", "").strip()]
    if boxes:
        a("## Pandora's Boxes and map events\n")
        for o in boxes:
            a(f"- ({o['x']},{o['y']},{o['z']}) [{o['name']}] {o['message'].strip()}")
            if detail_of(o) != "empty":
                a(f"  - *contains:* {detail_of(o)}")
        a("")

    guarded = [o for o in m["objects"]
               if o.get("message", "").strip() and o["object_id"] not in
               (91, 59, 54, 71, 72, 73, 74, 75, 162, 163, 164, 6, 26, 83)]
    if guarded:
        a("## Other object messages (guarded treasure etc.)\n")
        for o in guarded:
            a(f"- ({o['x']},{o['y']},{o['z']}) [{o['name']}] {o['message'].strip()}")
        a("")

    named = [o for o in objs(98, 77) if o.get("town_name")]
    if named:
        a("## Custom town names\n")
        for o in named:
            a(f"- ({o['x']},{o['y']},{o['z']}) {o.get('faction','?')} "
              f"[{o.get('owner','?')}] — {o['town_name']}")
        a("")

    heroes = [o for o in objs(34, 70, 62) if o.get("hero_name") or o.get("biography")]
    if heroes:
        a("## Custom hero names and biographies\n")
        for o in heroes:
            a(f"- ({o['x']},{o['y']},{o['z']}) [{o.get('owner','?')}] "
              f"**{o.get('hero_name') or hname(o.get('hero_id'))}** "
              f"(base: {hname(o.get('hero_id'))})")
            if o.get("biography"):
                a(f"  - {o['biography'].strip()}")
        a("")

    tevents = [(o, e) for o in objs(98) for e in o.get("events", [])]
    if tevents:
        a("## Town events\n")
        for o, e in tevents:
            a(f"- ({o['x']},{o['y']},{o['z']}) {o.get('town_name') or o.get('faction')}"
              f" — **{e['name']}** (day {e['first_occurrence'] + 1})"
              + (f": {e['message'].strip()}" if e["message"].strip() else ""))
        a("")

    return "\n".join(L)


def armies_rows(m):
    """Every creature stack on the map, from any source."""
    rows = []

    def add(o, source, cid, count, extra=""):
        rows.append({"x": o["x"], "y": o["y"], "z": o["z"], "source": source,
                     "owner": o.get("owner", ""), "creature_id": cid,
                     "creature": cname(cid) if cid is not None else "random",
                     "count": count, "notes": extra})

    for o in m["objects"]:
        oid = o["object_id"]
        if oid == 54:
            add(o, "Wandering monster", o["object_subid"], o.get("count", 0),
                f"{o.get('disposition','')}"
                + (", never flees" if o.get("never_flees") else "")
                + (", no growth" if o.get("does_not_grow") else "")
                + (", has message" if o.get("message") else ""))
        elif oid in (71, 72, 73, 74, 75, 162, 163, 164):
            add(o, "Random monster", None, o.get("count", 0), o["name"])
        elif oid in (33, 219):
            for s in o.get("army", []):
                add(o, "Garrison", s["creature_id"], s["count"],
                    "removable" if o.get("removable_units") else "locked")
        elif oid in (98, 77):
            for s in o.get("army", []):
                add(o, "Town garrison", s["creature_id"], s["count"],
                    o.get("town_name") or o.get("faction", ""))
        elif oid in (34, 70, 62):
            for s in o.get("army", []):
                add(o, "Hero army", s["creature_id"], s["count"],
                    o.get("hero_name") or hname(o.get("hero_id")))
        for s in o.get("guards", []):
            add(o, "Guarding " + o["name"], s["creature_id"], s["count"], "")
        for s in o.get("creatures", []):
            if isinstance(s, dict) and "creature_id" in s:
                add(o, o["name"] + " reward", s["creature_id"], s["count"], "")
    return rows


# --------------------------------------------------------------------------
# Full export
# --------------------------------------------------------------------------
def footprint(tpl):
    """Tiles an object covers, relative to its stored anchor position.

    Each template stores a 6-row x 8-column mask. The bottom-right cell of that
    grid is the object's stored (anchor) position, so offsets run -7..0 in x
    and -5..0 in y. A cleared bit in the block mask means the tile is blocked.
    """
    out = []
    for row in range(6):
        b, v = tpl["block_mask"][row], tpl["visit_mask"][row]
        for col in range(8):
            blocked = not ((b >> col) & 1)
            visitable = bool((v >> col) & 1)
            if blocked or visitable:
                out.append((col - 7, row - 5, blocked, visitable))
    return out


def object_creatures(o):
    """Creature stacks belonging to an object, normalised."""
    out = []
    oid = o["object_id"]
    if oid == 54:
        out.append({"source": "Wandering monster",
                    "creature_id": o["object_subid"],
                    "creature": cname(o["object_subid"]),
                    "count": o.get("count", 0),
                    "random_count": not o.get("count", 0),
                    "disposition": o.get("disposition")})
    elif oid in (71, 72, 73, 74, 75, 162, 163, 164):
        out.append({"source": "Random monster", "creature_id": None,
                    "creature": "random", "count": o.get("count", 0),
                    "random_count": not o.get("count", 0),
                    "tier": o["name"], "disposition": o.get("disposition")})
    for key, label in (("army", "Garrison"), ("guards", "Guards"),
                       ("creatures", "Reward")):
        for s in o.get(key) or []:
            if isinstance(s, dict) and "creature_id" in s:
                if key == "army":
                    label = ("Hero army" if oid in (34, 70, 62)
                             else "Town garrison" if oid in (98, 77)
                             else "Garrison")
                out.append({"source": label, "creature_id": s["creature_id"],
                            "creature": s["creature"], "count": s["count"],
                            "random_count": False})
    return out


def full_export(m, occupied_only=False, slim=False):
    """One big normalised dictionary describing everything in the map."""
    size, levels = m["size"], m["levels"]

    export = {}

    export["meta"] = {
        "name": m["name"], "version": m["version_name"],
        "version_id": m["version"], "size": size, "levels": levels,
        "has_underground": m["has_underground"], "difficulty": m["difficulty"],
        "max_hero_level": m["max_hero_level"] or None,
        "victory_condition": m["victory_condition"],
        "loss_condition": m["loss_condition"],
        "team_count": m["team_count"], "teams": m["teams"],
        "object_count": len(m["objects"]), "tile_count": size * size * levels,
    }

    export["players"] = m["players"]

    export["restrictions"] = {
        "allowed_heroes": [{"id": i, "name": hname(i)} for i in m["allowed_heroes"]],
        "allowed_artifacts": [{"id": i, "name": aname(i)} for i in m["allowed_artifacts"]],
        "allowed_spells": [{"id": i, "name": spname(i)} for i in m["allowed_spells"]],
        "allowed_skills": [{"id": i, "name": sname(i)} for i in m["allowed_skills"]],
        "disposed_heroes": m.get("disposed_heroes", []),
        "custom_hero_settings": m["hero_settings"],
    }

    # ---------------- story ----------------
    def pick(*ids):
        return [o for o in m["objects"] if o["object_id"] in ids]

    def at(o):
        return {"x": o["x"], "y": o["y"], "z": o["z"]}

    story = {"description": m["description"], "rumors": m["rumors"]}
    story["timed_events"] = [
        {"name": e["name"], "text": e["message"], "day": e["first_occurrence"] + 1,
         "repeat_every_days": e["repeat_after"] or None,
         "players": e["players"],
         "resources": {k: v for k, v in e["resources"].items() if v}}
        for e in m["global_events"]]
    story["signs_and_bottles"] = [
        dict(at(o), type=o["name"], text=o["message"])
        for o in pick(91, 59) if o.get("message", "").strip()]
    story["seer_huts"] = [
        dict(at(o), quest=o.get("quest", {}).get("mission"),
             requirement=quest_requirement(o.get("quest", {})),
             reward=detail_of(o).split("-> ")[-1],
             on_arrival=o.get("quest", {}).get("first_visit_text", ""),
             on_return=o.get("quest", {}).get("next_visit_text", ""),
             on_completion=o.get("quest", {}).get("completed_text", ""))
        for o in pick(83)]
    story["monster_messages"] = [
        dict(at(o), stack=detail_of(o), text=o["message"])
        for o in pick(54, 71, 72, 73, 74, 75, 162, 163, 164)
        if o.get("message", "").strip()]
    story["pandoras_and_events"] = [
        dict(at(o), type=o["name"], text=o.get("message", ""),
             contents=detail_of(o))
        for o in pick(6, 26) if o.get("message", "").strip()]
    story["town_events"] = [
        dict(at(o), town=o.get("town_name") or o.get("faction"),
             name=e["name"], text=e["message"], day=e["first_occurrence"] + 1,
             repeat_every_days=e["repeat_after"] or None)
        for o in pick(98) for e in o.get("events", [])]
    story["hero_biographies"] = [
        dict(at(o), hero=o.get("hero_name") or hname(o.get("hero_id")),
             base_hero=hname(o.get("hero_id")), text=o["biography"])
        for o in pick(34, 70, 62) if o.get("biography")]
    skip = {91, 59, 54, 71, 72, 73, 74, 75, 162, 163, 164, 6, 26, 83}
    story["other_messages"] = [
        dict(at(o), type=o["name"], text=o["message"])
        for o in m["objects"]
        if o.get("message", "").strip() and o["object_id"] not in skip]
    export["story"] = story

    # ---------------- objects (full detail, keyed by index) ----------------
    objects = {}
    for o in m["objects"]:
        rec = {k: v for k, v in o.items() if k != "index"}
        rec["summary"] = detail_of(o)
        tpl = m["templates"][o["template_index"]]
        tiles = []
        for dx, dy, blocked, visitable in footprint(tpl):
            tx, ty = o["x"] + dx, o["y"] + dy
            if 0 <= tx < size and 0 <= ty < size:
                tiles.append({"x": tx, "y": ty, "z": o["z"],
                              "blocked": blocked, "visitable": visitable})
        if not tiles:
            # overlays (magic terrain, etc.) carry an empty mask; they still
            # sit on their anchor tile
            tiles.append({"x": o["x"], "y": o["y"], "z": o["z"],
                          "blocked": False, "visitable": False})
        if not slim:
            rec["occupies"] = tiles
        rec["_tiles"] = tiles
        rec["visitable_tiles"] = [t for t in tiles if t["visitable"]]
        creatures = object_creatures(o)
        if creatures:
            rec["creatures"] = creatures
        objects[str(o["index"])] = rec
    export["objects"] = objects

    # ---------------- map (tile keyed "x,y,z") ----------------
    terrain_by_tile = {}
    for (x, y, z, t, tv, rv, rd, rt, rdd, fl) in m["terrain"]:
        terrain_by_tile[(x, y, z)] = {
            "terrain": TERRAIN[t] if t < len(TERRAIN) else t,
            "terrain_id": t, "variant": tv,
            "river": RIVER[rv] if rv < len(RIVER) else rv,
            "road": ROAD[rt] if rt < len(ROAD) else rt,
        }

    tile_objects = {}
    for idx, rec in objects.items():
        anchor = (rec["x"], rec["y"], rec["z"])
        for t in rec["_tiles"]:
            key = (t["x"], t["y"], t["z"])
            entry = {"index": int(idx), "name": rec["name"],
                     "object_id": rec["object_id"],
                     "subid": rec["object_subid"],
                     "role": "anchor" if key == anchor else "footprint",
                     "blocked": t["blocked"], "visitable": t["visitable"]}
            if not slim:
                if rec["summary"]:
                    entry["summary"] = rec["summary"]
                if rec.get("owner"):
                    entry["owner"] = rec["owner"]
            tile_objects.setdefault(key, []).append(entry)
        if rec.get("creatures"):
            for c in rec["creatures"]:
                tile_objects.setdefault(anchor, [])
    tile_creatures = {}
    for idx, rec in objects.items():
        if rec.get("creatures"):
            key = (rec["x"], rec["y"], rec["z"])
            for c in rec["creatures"]:
                tile_creatures.setdefault(key, []).append(dict(c, object_index=int(idx)))

    tiles = {}
    for z in range(levels):
        for y in range(size):
            for x in range(size):
                key = (x, y, z)
                objs = tile_objects.get(key)
                crs = tile_creatures.get(key)
                if occupied_only and not objs and not crs:
                    continue
                node = {"terrain": terrain_by_tile.get(key, {})}
                if objs:
                    node["objects"] = objs
                if crs:
                    node["creatures"] = crs
                tiles[f"{x},{y},{z}"] = node
    export["map"] = tiles

    # ---------------- themed indexes ----------------
    def index(*ids, **extra):
        out = []
        for o in m["objects"]:
            if o["object_id"] in ids:
                out.append(dict(at(o), index=o["index"], type=o["name"],
                                summary=detail_of(o), **{k: o.get(k) for k in extra}))
        return out

    export["heroes"] = [
        dict(at(o), index=o["index"], type=o["name"],
             hero_id=o.get("hero_id"), base_hero=hname(o.get("hero_id")),
             name=o.get("hero_name") or hname(o.get("hero_id")),
             owner=o.get("owner"), experience=o.get("experience"),
             patrol_radius=o.get("patrol_radius"),
             primary_skills=o.get("primary_skills"),
             secondary_skills=o.get("secondary_skills"),
             spells=[spname(s) for s in o.get("spells", [])],
             artifacts=o.get("artifacts"), army=o.get("army", []))
        for o in pick(34, 70, 62)]

    export["towns"] = [
        dict(at(o), index=o["index"], faction=o.get("faction"),
             name=o.get("town_name"), owner=o.get("owner"),
             has_fort=o.get("has_fort"),
             built=[bname(b) for b in o.get("buildings_built", [])],
             forbidden=[bname(b) for b in o.get("buildings_forbidden", [])],
             garrison=o.get("army", []), event_count=len(o.get("events", [])))
        for o in pick(98, 77)]

    export["monsters"] = [
        dict(at(o), index=o["index"], type=o["name"],
             creature_id=o["object_subid"] if o["object_id"] == 54 else None,
             creature=cname(o["object_subid"]) if o["object_id"] == 54 else "random",
             count=o.get("count", 0), random_count=not o.get("count", 0),
             disposition=o.get("disposition"),
             never_flees=o.get("never_flees"), does_not_grow=o.get("does_not_grow"),
             message=o.get("message", ""))
        for o in pick(54, 71, 72, 73, 74, 75, 162, 163, 164)]

    export["mines"] = index(53, 220, owner=None, mine_type=None, resources=None)
    export["dwellings"] = index(17, 18, 19, 20, 216, 217, 218, owner=None)
    export["artifacts"] = [
        dict(at(o), index=o["index"], type=o["name"],
             artifact_id=o["object_subid"] if o["object_id"] == 5 else None,
             artifact=aname(o["object_subid"]) if o["object_id"] == 5 else "random",
             spell=spname(o["spell_id"]) if o["object_id"] == 93 else None,
             guards=o.get("guards", []), message=o.get("message", ""))
        for o in pick(5, 65, 66, 67, 68, 69, 93)]
    export["resources"] = [
        dict(at(o), index=o["index"],
             resource=RESOURCES[o["object_subid"]] if o["object_subid"] < 7 else "random",
             amount=o.get("amount", 0), random_amount=not o.get("amount", 0),
             guards=o.get("guards", []))
        for o in pick(79, 76)]
    export["quests"] = [
        dict(at(o), index=o["index"], type=o["name"],
             mission=o.get("quest", {}).get("mission"),
             requirement=quest_requirement(o.get("quest", {})),
             reward=detail_of(o).split("-> ")[-1] if o["object_id"] == 83 else None)
        for o in pick(83, 215)]

    # ---------------- statistics ----------------
    creature_totals = Counter()
    for rec in objects.values():
        for c in rec.get("creatures", []):
            if c["creature"] != "random":
                creature_totals[c["creature"]] += c["count"]
    stats = {
        "objects_by_type": dict(Counter(o["name"] for o in m["objects"]).most_common()),
        "terrain_distribution": dict(Counter(
            TERRAIN[t[3]] if t[3] < len(TERRAIN) else t[3] for t in m["terrain"])),
        "tiles_with_objects": len(tile_objects),
        "towns_by_player": dict(Counter(o.get("owner", "?") for o in pick(98, 77))),
        "mines_by_player": dict(Counter(o.get("owner", "?") for o in pick(53))),
        "heroes_by_player": dict(Counter(o.get("owner", "?") for o in pick(34, 70, 62))),
        "creature_totals": dict(creature_totals.most_common()),
        "total_creatures": sum(creature_totals.values()),
        "text_blocks": {k: len(v) for k, v in story.items() if isinstance(v, list)},
    }
    export["statistics"] = stats
    for rec in objects.values():
        rec.pop("_tiles", None)
    return export


def main():
    ap = argparse.ArgumentParser(description="Read Heroes of Might & Magic III .h3m maps")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--objects", action="store_true", help="print every object")
    ap.add_argument("--filter", help="only objects whose type contains this text")
    ap.add_argument("--json", help="write full structured dump to this file")
    ap.add_argument("--csv", help="write object list to this CSV")
    ap.add_argument("--terrain-csv", help="write per-tile terrain to this CSV")
    ap.add_argument("--export-texts", metavar="FILE",
                    help="write every editable string to a JSON file")
    ap.add_argument("--import-texts", metavar="FILE",
                    help="apply an edited text file (needs --save)")
    ap.add_argument("--save", metavar="FILE.h3m",
                    help="write the map back out, with any edits applied")
    ap.add_argument("--texts", help="write all story/message text to this Markdown file")
    ap.add_argument("--armies", help="write every creature stack to this CSV")
    ap.add_argument("--export", help="write the full tile-keyed JSON export here")
    ap.add_argument("--occupied-only", action="store_true",
                    help="with --export, omit map tiles that hold no object")
    ap.add_argument("--slim", action="store_true",
                    help="with --export, drop data derivable by index lookup")
    ap.add_argument("--compact", action="store_true",
                    help="with --export, write minified JSON")
    args = ap.parse_args()

    for path in args.files:
        m = parse_file(path)
        print(summarise(m, path))
        rows = objects_table(m)
        if args.objects:
            print("\nAll objects:")
            print(f"{'x':>4} {'y':>4} {'z':>2}  {'type':<28} {'owner':<13} detail")
            for r in rows:
                if args.filter and args.filter.lower() not in r["type"].lower():
                    continue
                print(f"{r['x']:>4} {r['y']:>4} {r['z']:>2}  {r['type']:<28} "
                      f"{r['owner']:<13} {r['detail']}")
        if args.json:
            out = dict(m)
            out["terrain"] = f"<{len(m['terrain'])} tiles omitted; use --terrain-csv>"
            with open(args.json, "w") as f:
                json.dump(out, f, indent=1, default=str)
            print(f"\nwrote {args.json}")
        if args.csv:
            with open(args.csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
            print(f"wrote {args.csv}")
        if args.export_texts:
            export_texts(m, args.export_texts)
            print(f"wrote {args.export_texts} "
                  f"({len(_text_targets(m))} strings)")
        if args.import_texts:
            changes = import_texts(m, args.import_texts)
            print(f"queued {len(changes)} text change(s)")
            for c in changes[:10]:
                print(f"   {c['where']}")
        if args.save:
            save(m, args.save)
            print(f"wrote {args.save} "
                  f"({len(pending_edits(m))} change(s) applied)")
        if args.export:
            ex = full_export(m, occupied_only=args.occupied_only, slim=args.slim)
            with open(args.export, "w") as f:
                json.dump(ex, f, indent=None if args.compact else 1, default=str)
            print(f"wrote {args.export} "
                  f"({len(ex['map'])} tiles, {len(ex['objects'])} objects, "
                  f"{os.path.getsize(args.export) / 1e6:.1f} MB)")
        if args.texts:
            with open(args.texts, "w") as f:
                f.write(texts_report(m, path))
            print(f"wrote {args.texts}")
        if args.armies:
            arows = armies_rows(m)
            with open(args.armies, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(arows[0].keys()))
                w.writeheader(); w.writerows(arows)
            print(f"wrote {args.armies} ({len(arows)} stacks)")
        if args.terrain_csv:
            with open(args.terrain_csv, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["x", "y", "z", "terrain", "terrain_id", "variant",
                            "river", "river_dir", "road", "road_dir", "flags"])
                for (x, y, z, t, tv, rv, rd, rt, rdd, fl) in m["terrain"]:
                    w.writerow([x, y, z,
                                TERRAIN[t] if t < len(TERRAIN) else t, t, tv,
                                RIVER[rv] if rv < len(RIVER) else rv, rd,
                                ROAD[rt] if rt < len(ROAD) else rt, rdd, fl])
            print(f"wrote {args.terrain_csv}")
        print("\n" + "=" * 78 + "\n")


if __name__ == "__main__":
    main()
