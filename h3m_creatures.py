"""
h3m_creatures.py — creature reference data.

AI Values are the game's own creature valuation, transcribed from the
"Tribute to Strategists" manual (Rainalkar, 2008). Combat stats come from
the Heroes 3 creature power chart. Both are keyed by h3m creature id.

Note: the power chart's own ID column does not match h3m ids (its Fortress
and Conflux orderings differ), so this table was built by matching names.
"""

# id: (name, ai_value, level, speed, hp, attack, defence, avg_dmg, growth, cost)
CREATURE_DATA = {
    0: ('Pikeman', 80, 1, 4, 10, 4, 5, 2, 28, 60),
    1: ('Halberdier', 115, 1, 5, 10, 6, 5, 2.5, 28, 75),
    2: ('Archer', 126, 2, 4, 10, 6, 3, 2.5, 18, 100),
    3: ('Marksman', 184, 2, 6, 10, 6, 3, 5, 18, 150),
    4: ('Griffin', 351, 3, 6, 25, 8, 8, 4.5, 17, 200),
    5: ('Royal Griffin', 448, 3, 9, 25, 9, 9, 4.5, 17, 240),
    6: ('Swordsman', 445, 4, 5, 35, 10, 12, 7.5, 8, 300),
    7: ('Crusader', 588, 4, 6, 35, 12, 12, 17, 8, 400),
    8: ('Monk', 485, 5, 5, 30, 12, 7, 11, 6, 400),
    9: ('Zealot', 750, 5, 7, 30, 12, 10, 11, 6, 450),
    10: ('Cavalier', 1946, 6, 7, 100, 15, 15, 20, 4, 1000),
    11: ('Champion', 2100, 6, 9, 100, 16, 16, 22.5, 4, 1200),
    12: ('Angel', 5019, 7, 12, 200, 20, 20, 50, 2, 3000),
    13: ('Archangel', 8776, 7, 18, 250, 30, 30, 50, 2, 5000),
    14: ('Centaur', 100, 1, 6, 8, 5, 3, 2.5, 28, 70),
    15: ('Centaur Captain', 138, 1, 8, 10, 6, 3, 2.5, 28, 90),
    16: ('Dwarf', 138, 2, 3, 20, 6, 7, 3, 20, 120),
    17: ('Battle Dwarf', 209, 2, 5, 20, 7, 7, 3, 20, 150),
    18: ('Wood Elf', 234, 3, 6, 15, 9, 5, 4, 14, 200),
    19: ('Grand Elf', 331, 3, 7, 15, 9, 5, 8, 14, 225),
    20: ('Pegasus', 518, 4, 8, 30, 9, 8, 7, 10, 250),
    21: ('Silver Pegasus', 532, 4, 12, 30, 9, 10, 7, 10, 275),
    22: ('Dendroid Guard', 517, 5, 3, 55, 9, 12, 12, 8, 350),
    23: ('Dendroid Soldier', 803, 5, 4, 65, 9, 12, 12, 8, 425),
    24: ('Unicorn', 1806, 6, 7, 90, 15, 14, 20, 4, 850),
    25: ('War Unicorn', 2030, 6, 9, 110, 15, 14, 20, 4, 950),
    26: ('Green Dragon', 4872, 7, 10, 180, 18, 18, 45, 2, 2400),
    27: ('Gold Dragon', 8613, 7, 16, 250, 27, 27, 45, 2, 4000),
    28: ('Gremlin', 44, 1, 4, 4, 3, 3, 1.5, 32, 30),
    29: ('Master Gremlin', 66, 1, 5, 4, 4, 4, 1.5, 32, 40),
    30: ('Stone Gargoyle', 165, 2, 6, 16, 6, 6, 2.5, 22, 130),
    31: ('Obsidian Gargoyle', 201, 2, 9, 16, 7, 7, 2.5, 22, 160),
    32: ('Stone Golem', 250, 3, 3, 30, 7, 10, 4.5, 12, 150),
    33: ('Iron Golem', 412, 3, 5, 35, 9, 10, 4.5, 12, 200),
    34: ('Mage', 570, 4, 5, 25, 11, 8, 8, 8, 350),
    35: ('Arch Mage', 680, 4, 7, 30, 12, 9, 8, 8, 450),
    36: ('Genie', 884, 5, 7, 40, 12, 12, 14.5, 6, 550),
    37: ('Master Genie', 942, 5, 11, 40, 12, 12, 14.5, 6, 600),
    38: ('Naga', 2016, 6, 5, 110, 16, 13, 20, 4, 1100),
    39: ('Naga Queen', 2840, 6, 7, 110, 16, 13, 30, 4, 1600),
    40: ('Giant', 3718, 7, 7, 150, 19, 16, 50, 2, 2000),
    41: ('Titan', 7500, 7, 11, 300, 24, 24, 50, 2, 5000),
    42: ('Imp', 50, 1, 5, 4, 2, 3, 1.5, 38, 50),
    43: ('Familiar', 60, 1, 7, 4, 4, 4, 1.5, 38, 60),
    44: ('Gog', 159, 2, 4, 13, 6, 4, 3, 16, 125),
    45: ('Magog', 240, 2, 6, 13, 7, 4, 3, 16, 175),
    46: ('Hell Hound', 357, 3, 7, 25, 10, 6, 4.5, 13, 200),
    47: ('Cerberus', 392, 3, 8, 25, 10, 8, 4.5, 13, 250),
    48: ('Demon', 445, 4, 5, 35, 10, 10, 8, 8, 250),
    49: ('Horned Demon', 480, 4, 6, 40, 10, 10, 8, 8, 270),
    50: ('Pit Fiend', 765, 5, 6, 45, 13, 13, 15, 6, 500),
    51: ('Pit Lord', 1224, 5, 7, 45, 13, 13, 15, 6, 700),
    52: ('Efreeti', 1670, 6, 9, 90, 16, 12, 20, 4, 900),
    53: ('Efreet Sultan', 1848, 6, 13, 90, 16, 14, 20, 4, 1100),
    54: ('Devil', 5101, 7, 11, 160, 19, 21, 35, 2, 2700),
    55: ('Arch Devil', 7115, 7, 17, 200, 26, 28, 35, 2, 4500),
    56: ('Skeleton', 60, 1, 4, 6, 5, 4, 2, 30, 60),
    57: ('Skeleton Warrior', 85, 1, 5, 6, 6, 6, 2, 30, 70),
    58: ('Walking Dead', 98, 2, 3, 15, 5, 5, 2.5, 16, 100),
    59: ('Zombie', 128, 2, 4, 20, 5, 5, 2.5, 16, 125),
    60: ('Wight', 252, 3, 5, 18, 7, 7, 4, 14, 200),
    61: ('Wraith', 315, 3, 7, 18, 7, 7, 4, 14, 230),
    62: ('Vampire', 555, 4, 6, 30, 10, 9, 6.5, 8, 360),
    63: ('Vampire Lord', 783, 4, 9, 40, 10, 10, 6.5, 8, 500),
    64: ('Lich', 848, 5, 6, 30, 13, 10, 12, 6, 550),
    65: ('Power Lich', 1079, 5, 7, 40, 13, 10, 13, 6, 600),
    66: ('Black Knight', 2087, 6, 7, 120, 16, 16, 22.5, 4, 1200),
    67: ('Dread Knight', 2382, 6, 9, 120, 18, 18, 22.5, 4, 1500),
    68: ('Bone Dragon', 3388, 7, 9, 150, 17, 15, 37.5, 2, 1800),
    69: ('Ghost Dragon', 4696, 7, 14, 200, 19, 17, 37.5, 2, 3000),
    70: ('Troglodyte', 59, 1, 4, 5, 4, 3, 2, 35, 50),
    71: ('Infernal Troglodyte', 84, 1, 6, 6, 5, 4, 2, 35, 65),
    72: ('Harpy', 154, 2, 6, 14, 6, 5, 2.5, 16, 130),
    73: ('Harpy Hag', 238, 2, 9, 14, 6, 6, 2.5, 16, 170),
    74: ('Beholder', 336, 3, 5, 22, 9, 7, 4, 14, 250),
    75: ('Evil Eye', 367, 3, 7, 22, 10, 8, 4, 14, 280),
    76: ('Medusa', 517, 4, 5, 25, 9, 9, 7, 8, 300),
    77: ('Medusa Queen', 577, 4, 6, 30, 10, 10, 7, 8, 330),
    78: ('Minotaur', 835, 5, 6, 50, 14, 12, 16, 6, 500),
    79: ('Minotaur King', 1068, 5, 8, 50, 15, 15, 16, 6, 575),
    80: ('Manticore', 1547, 6, 7, 80, 15, 13, 17, 4, 850),
    81: ('Scorpicore', 1589, 6, 11, 80, 16, 14, 17, 4, 1050),
    82: ('Red Dragon', 4702, 7, 11, 180, 19, 19, 45, 2, 2500),
    83: ('Black Dragon', 8721, 7, 15, 300, 25, 25, 45, 2, 4000),
    84: ('Goblin', 60, 1, 5, 5, 4, 2, 1.5, 38, 40),
    85: ('Hobgoblin', 78, 1, 7, 5, 5, 3, 1.5, 38, 50),
    86: ('Wolf Rider', 130, 2, 6, 10, 7, 5, 3, 18, 100),
    87: ('Wolf Raider', 203, 2, 8, 10, 8, 5, 7, 18, 140),
    88: ('Orc', 192, 3, 4, 15, 8, 4, 3.5, 14, 150),
    89: ('Orc Chieftain', 240, 3, 5, 20, 8, 4, 3.5, 14, 165),
    90: ('Ogre', 416, 4, 4, 40, 13, 7, 9, 8, 300),
    91: ('Ogre Mage', 672, 4, 5, 60, 13, 7, 9, 8, 400),
    92: ('Roc', 1027, 5, 7, 60, 13, 11, 13, 6, 600),
    93: ('Thunderbird', 1106, 5, 11, 60, 13, 11, 13, 6, 700),
    94: ('Cyclops', 1266, 6, 6, 70, 15, 12, 18, 4, 750),
    95: ('Cyclops King', 1443, 6, 8, 70, 17, 13, 18, 4, 1100),
    96: ('Behemoth', 3162, 7, 6, 160, 17, 17, 40, 2, 1500),
    97: ('Ancient Behemoth', 6168, 7, 9, 300, 19, 19, 40, 2, 3000),
    98: ('Gnoll', 56, 1, 4, 6, 3, 5, 2.5, 30, 50),
    99: ('Gnoll Marauder', 90, 1, 5, 6, 4, 6, 2.5, 30, 70),
    100: ('Lizardman', 126, 2, 5, 14, 5, 6, 2.5, 18, 110),
    101: ('Lizard Warrior', 156, 2, 5, 15, 6, 8, 3.5, 18, 140),
    102: ('Gorgon', 890, 5, 5, 70, 10, 14, 14, 6, 525),
    103: ('Mighty Gorgon', 1028, 5, 6, 70, 11, 16, 14, 6, 600),
    104: ('Serpent Fly', 268, 3, 9, 20, 7, 9, 3.5, 16, 220),
    105: ('Dragon Fly', 312, 3, 13, 20, 8, 10, 3.5, 16, 240),
    106: ('Basilisk', 552, 4, 5, 35, 11, 11, 8, 8, 325),
    107: ('Greater Basilisk', 714, 4, 7, 40, 12, 12, 8, 8, 400),
    108: ('Wyvern', 1350, 6, 7, 70, 14, 14, 16, 4, 800),
    109: ('Wyvern Monarch', 1518, 6, 11, 70, 14, 14, 20, 4, 1100),
    110: ('Hydra', 4120, 7, 5, 175, 16, 18, 35, 2, 2200),
    111: ('Chaos Hydra', 5931, 7, 7, 250, 18, 20, 35, 2, 3500),
    112: ('Air Elemental', 356, 2, 7, 25, 9, 9, 5, 12, 250),
    113: ('Earth Elemental', 330, 5, 4, 40, 10, 10, 6, 8, 400),
    114: ('Fire Elemental', 345, 4, 6, 35, 10, 8, 5, 10, 350),
    115: ('Water Elemental', 315, 3, 5, 30, 8, 10, 5, 12, 300),
    116: ('Gold Golem', 600, 5, 5, 50, 11, 12, 9, 3, 500),
    117: ('Diamond Golem', 775, 6, 5, 60, 13, 12, 12, 2, 750),
    118: ('Pixie', 55, 1, 7, 3, 2, 2, 1.5, 50, 25),
    119: ('Sprite', 95, 1, 9, 3, 2, 2, 2, 50, 30),
    120: ('Psychic Elemental', 1669, 6, 7, 75, 15, 13, 15, 4, 750),
    121: ('Magic Elemental', 2012, 6, 9, 80, 15, 13, 20, 4, 800),
    123: ('Ice Elemental', 380, 3, 6, 30, 8, 10, 5, 12, 375),
    125: ('Magma Elemental', 490, 5, 6, 40, 11, 11, 8, 8, 500),
    127: ('Storm Elemental', 486, 2, 8, 25, 9, 9, 5, 12, 275),
    129: ('Energy Elemental', 470, 4, 8, 35, 12, 8, 5, 10, 400),
    130: ('Firebird', 4547, 7, 15, 150, 18, 18, 35, 4, 1500),
    131: ('Phoenix', 6721, 7, 21, 200, 21, 18, 35, 4, 2000),
    132: ('Azure Dragon', 78845, 7, 19, 1000, 50, 50, 75, 1, 30000),
    133: ('Crystal Dragon', 39338, 7, 16, 800, 40, 40, 67.5, 1, 20000),
    134: ('Faerie Dragon', 19580, 7, 15, 500, 20, 20, 25, 1, 10000),
    135: ('Rust Dragon', 26433, 7, 17, 750, 30, 30, 50, 1, 15000),
    136: ('Enchanter', 1210, 6, 9, 30, 17, 12, 14, 2, 750),
    137: ('Sharpshooter', 585, 4, 9, 15, 12, 10, 9, 4, 400),
    138: ('Halfling', 75, 1, 5, 4, 4, 2, 2, 15, 40),
    139: ('Peasant', 15, 1, 3, 1, 1, 1, 1, 25, 10),
    140: ('Boar', 145, 2, 6, 15, 6, 5, 2.5, 8, 150),
    141: ('Mummy', 270, 3, 5, 30, 7, 7, 4, 7, 300),
    142: ('Nomad', 345, 3, 7, 30, 9, 8, 4, 7, 200),
    143: ('Rogue', 135, 2, 6, 10, 8, 3, 3, 8, 100),
    144: ('Troll', 1024, 5, 7, 40, 14, 7, 12.5, 3, 500),
    145: ('Catapult', 500, None, None, None, None, None, None, None, None),
    146: ('Ballista', 600, None, None, None, None, None, None, None, None),
    147: ('First Aid Tent', 300, None, None, None, None, None, None, None, None),
    148: ('Ammo Cart', 400, None, None, None, None, None, None, None, None),
    149: ('Arrow Tower', 400, None, None, None, None, None, None, None, None),
}

# --------------------------------------------------------------------------
# Traits (curated; used as modifiers and for reporting)
# --------------------------------------------------------------------------
RANGED = {
    2, 3, 8, 9, 18, 19, 29, 34, 35, 41, 44, 45, 64, 65, 74, 75, 76, 77,
    88, 89, 92, 93, 100, 101, 123, 127, 136, 137, 138, 146, 149,
}
FLYING = {
    4, 5, 12, 13, 20, 21, 26, 27, 30, 31, 36, 37, 52, 53, 54, 55,
    60, 61, 62, 63, 68, 69, 72, 73, 80, 81, 82, 83, 90, 91,
    104, 105, 108, 109, 118, 119, 129, 130, 131, 132, 133, 134, 135,
}

# --------------------------------------------------------------------------
# Effective power
# --------------------------------------------------------------------------
# AI Value is the game's own yardstick and the right starting point, but it
# undervalues mobility: a Dendroid Soldier (AI 803, speed 4) rates above a
# Vampire Lord (AI 783, speed 9, flying) even though the Vampire Lord is far
# more dangerous in practice. These modifiers correct for that.
SPEED_REFERENCE = 6.5      # roughly the median creature speed
SPEED_EXPONENT = 0.5       # 0 = ignore speed, 1 = power scales linearly with it
RANGED_BONUS = 1.15
FLYING_BONUS = 1.10

MEDIAN_SPEED = 6.5


def stat(cid, key):
    """One field for a creature id, or None."""
    row = CREATURE_DATA.get(cid)
    if not row:
        return None
    fields = ("name", "ai_value", "level", "speed", "hp", "attack",
              "defence", "avg_dmg", "growth", "cost")
    try:
        return row[fields.index(key)]
    except (ValueError, IndexError):
        return None


def ai_value(cid):
    return stat(cid, "ai_value")


def power(cid, speed_exponent=SPEED_EXPONENT, ranged_bonus=RANGED_BONUS,
          flying_bonus=FLYING_BONUS):
    """Effective combat power: AI value adjusted for speed and traits.

    Returns None for creatures with no AI value (nothing is invented).
    """
    base = ai_value(cid)
    if base is None:
        return None
    p = float(base)
    spd = stat(cid, "speed")
    if spd:
        p *= (spd / SPEED_REFERENCE) ** speed_exponent
    if cid in RANGED:
        p *= ranged_bonus
    if cid in FLYING:
        p *= flying_bonus
    return p


def meta(cid):
    """Everything known about a creature id."""
    row = CREATURE_DATA.get(cid)
    if not row:
        return None
    (name, aiv, level, speed, hp, atk, dfn, dmg, growth, cost) = row
    return {"id": cid, "name": name, "ai_value": aiv, "level": level,
            "speed": speed, "hp": hp, "attack": atk, "defence": dfn,
            "avg_damage": dmg, "growth": growth, "cost": cost,
            "ranged": cid in RANGED, "flying": cid in FLYING,
            "power": power(cid)}

# --------------------------------------------------------------------------
# Artifact classes, transcribed from the Artifact Merchant price tables in
# "Tribute to Strategists". A Relic behind a guard is a very different reward
# from a Treasure artifact, and the balance model needs to know which.
# --------------------------------------------------------------------------
ARTIFACT_CLASS = {
    0: 'SPECIAL',   # Spellbook
    1: 'SPECIAL',   # Spell Scroll
    2: 'SPECIAL',   # Grail
    3: 'SPECIAL',   # Catapult
    4: 'SPECIAL',   # Ballista
    5: 'SPECIAL',   # Ammo Cart
    6: 'SPECIAL',   # First Aid Tent
    7: 'TREASURE',   # Centaur Axe
    8: 'MINOR',   # Blackshard of the Dead Knight
    9: 'MINOR',   # Greater Gnoll's Flail
    10: 'MAJOR',   # Ogre's Club of Havoc
    11: 'MAJOR',   # Sword of Hellfire
    12: 'RELIC',   # Titan's Gladius
    13: 'TREASURE',   # Shield of the Dwarven Lords
    14: 'MINOR',   # Shield of the Yawning Dead
    15: 'MINOR',   # Buckler of the Gnoll King
    16: 'MAJOR',   # Targ of the Rampaging Ogre
    17: 'MAJOR',   # Shield of the Damned
    18: 'RELIC',   # Sentinel's Shield
    19: 'TREASURE',   # Helm of the Alabaster Unicorn
    20: 'TREASURE',   # Skull Helmet
    21: 'MINOR',   # Helm of Chaos
    22: 'MINOR',   # Crown of the Supreme Magi
    23: 'MAJOR',   # Hellstorm Helmet
    24: 'RELIC',   # Thunder Helmet
    25: 'TREASURE',   # Breastplate of Petrified Wood
    26: 'MINOR',   # Rib Cage
    27: 'MINOR',   # Scales of the Greater Basilisk
    28: 'MAJOR',   # Tunic of the Cyclops King
    29: 'MAJOR',   # Breastplate of Brimstone
    30: 'RELIC',   # Titan's Cuirass
    31: 'MINOR',   # Armor of Wonder
    32: 'RELIC',   # Sandals of the Saint
    33: 'RELIC',   # Celestial Necklace of Bliss
    34: 'RELIC',   # Lion's Shield of Courage
    35: 'RELIC',   # Sword of Judgement
    36: 'RELIC',   # Helm of Heavenly Enlightenment
    37: 'TREASURE',   # Quiet Eye of the Dragon
    38: 'MINOR',   # Red Dragon Flame Tongue
    39: 'MAJOR',   # Dragon Scale Shield
    40: 'RELIC',   # Dragon Scale Armor
    41: 'TREASURE',   # Dragonbone Greaves
    42: 'MINOR',   # Dragon Wing Tabard
    43: 'MAJOR',   # Necklace of Dragonteeth
    44: 'RELIC',   # Crown of Dragontooth
    45: 'TREASURE',   # Still Eye of the Dragon
    46: 'TREASURE',   # Clover of Fortune
    47: 'TREASURE',   # Cards of Prophecy
    48: 'TREASURE',   # Ladybird of Luck
    49: 'TREASURE',   # Badge of Courage
    50: 'TREASURE',   # Crest of Valor
    51: 'TREASURE',   # Glyph of Gallantry
    52: 'TREASURE',   # Speculum
    53: 'TREASURE',   # Spyglass
    54: 'TREASURE',   # Amulet of the Undertaker
    55: 'MINOR',   # Vampire's Cowl
    56: 'MAJOR',   # Dead Man's Boots
    57: 'MAJOR',   # Garniture of Interference
    58: 'MAJOR',   # Surcoat of Counterpoise
    59: 'RELIC',   # Boots of Polarity
    60: 'TREASURE',   # Bow of Elven Cherrywood
    61: 'MINOR',   # Bowstring of the Unicorn's Mane
    62: 'MAJOR',   # Angel Feather Arrows
    63: 'TREASURE',   # Bird of Perception
    64: 'TREASURE',   # Stoic Watchman
    65: 'MINOR',   # Emblem of Cognizance
    66: 'MAJOR',   # Statesman's Medal
    67: 'MAJOR',   # Diplomat's Ring
    68: 'MAJOR',   # Ambassador's Sash
    69: 'MAJOR',   # Ring of the Wayfarer
    70: 'MINOR',   # Equestrian's Gloves
    71: 'MAJOR',   # Necklace of Ocean Guidance
    72: 'RELIC',   # Angel Wings
    73: 'TREASURE',   # Charm of Mana
    74: 'TREASURE',   # Talisman of Mana
    75: 'TREASURE',   # Mystic Orb of Mana
    76: 'TREASURE',   # Collar of Conjuring
    77: 'TREASURE',   # Ring of Conjuring
    78: 'TREASURE',   # Cape of Conjuring
    79: 'MAJOR',   # Orb of the Firmament
    80: 'MAJOR',   # Orb of Silt
    81: 'MAJOR',   # Orb of Tempestuous Fire
    82: 'MAJOR',   # Orb of Driving Rain
    83: 'MAJOR',   # Recanter's Cloak
    84: 'TREASURE',   # Spirit of Oppression
    85: 'TREASURE',   # Hourglass of the Evil Hour
    86: 'RELIC',   # Tome of Fire Magic
    87: 'RELIC',   # Tome of Air Magic
    88: 'RELIC',   # Tome of Water Magic
    89: 'RELIC',   # Tome of Earth Magic
    90: 'RELIC',   # Boots of Levitation
    91: 'MAJOR',   # Golden Bow
    92: 'MAJOR',   # Sphere of Permanence
    93: 'RELIC',   # Orb of Vulnerability
    94: 'TREASURE',   # Ring of Vitality
    95: 'MINOR',   # Ring of Life
    96: 'MAJOR',   # Vial of Lifeblood
    97: 'TREASURE',   # Necklace of Swiftness
    98: 'MINOR',   # Boots of Speed
    99: 'MAJOR',   # Cape of Velocity
    100: 'TREASURE',   # Pendant of Dispassion
    101: 'MAJOR',   # Pendant of Second Sight
    102: 'TREASURE',   # Pendant of Holiness
    103: 'TREASURE',   # Pendant of Life
    104: 'TREASURE',   # Pendant of Death
    105: 'TREASURE',   # Pendant of Free Will
    106: 'MAJOR',   # Pendant of Negativity
    107: 'TREASURE',   # Pendant of Total Recall
    108: 'MAJOR',   # Pendant of Courage
    109: 'MAJOR',   # Everflowing Crystal Cloak
    110: 'MAJOR',   # Ring of Infinite Gems
    111: 'MAJOR',   # Everpouring Vial of Mercury
    112: 'MINOR',   # Inexhaustible Cart of Ore
    113: 'MAJOR',   # Eversmoking Ring of Sulfur
    114: 'MINOR',   # Inexhaustible Cart of Lumber
    115: 'RELIC',   # Endless Sack of Gold
    116: 'MAJOR',   # Endless Bag of Gold
    117: 'MAJOR',   # Endless Purse of Gold
    118: 'TREASURE',   # Legs of Legion
    119: 'MINOR',   # Loins of Legion
    120: 'MINOR',   # Torso of Legion
    121: 'MAJOR',   # Arms of Legion
    122: 'MAJOR',   # Head of Legion
    123: 'RELIC',   # Sea Captain's Hat
    124: 'RELIC',   # Spellbinder's Hat
    125: 'MAJOR',   # Shackles of War
    126: 'RELIC',   # Orb of Inhibition
    127: 'RELIC',   # Vial of Dragon Blood
    128: 'RELIC',   # Armageddon's Blade
    129: 'COMBO',   # Angelic Alliance
    130: 'COMBO',   # Cloak of the Undead King
    131: 'COMBO',   # Elixir of Life
    132: 'COMBO',   # Armor of the Damned
    133: 'COMBO',   # Statue of Legion
    134: 'COMBO',   # Power of the Dragon Father
    135: 'COMBO',   # Titan's Thunder
    136: 'COMBO',   # Admiral's Hat
    137: 'COMBO',   # Bow of the Sharpshooter
    138: 'COMBO',   # Wizard's Well
    139: 'COMBO',   # Ring of the Magi
    140: 'COMBO',   # Cornucopia
}


# rough relative worth of each class, used only to order rewards
ARTIFACT_CLASS_RANK = {"SPECIAL": 0, "TREASURE": 1, "MINOR": 2, "MAJOR": 3,
                       "RELIC": 4, "COMBO": 5}


def artifact_class(artifact_id):
    return ARTIFACT_CLASS.get(artifact_id, "UNKNOWN")

