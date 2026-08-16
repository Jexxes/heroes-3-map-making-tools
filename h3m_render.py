"""
h3m_render.py — rendering logic shared by the GUI and the PNG preview tool.

Kept free of any GUI toolkit so it can be tested headlessly.
"""

import h3m

# --------------------------------------------------------------------------
# Palettes
# --------------------------------------------------------------------------
TERRAIN_COLORS = {
    "Dirt": "#7a5c34", "Sand": "#ddc890", "Grass": "#4a7a2b",
    "Snow": "#e2ecf2", "Swamp": "#3d6b57", "Rough": "#9a8248",
    "Subterranean": "#4a3b33", "Lava": "#463f3c", "Water": "#2a5c8a",
    "Rock": "#191919",
}
UNKNOWN_TERRAIN = "#ff00ff"

# offered in the GUI's owner dropdown
PLAYERS_FOR_EDIT = ["Red", "Blue", "Tan", "Green", "Orange", "Purple",
                    "Teal", "Pink", "Neutral/None"]

PLAYER_COLORS = {
    "Red": "#e03028", "Blue": "#2f5fdc", "Tan": "#c9a878", "Green": "#37a03c",
    "Orange": "#ef8420", "Purple": "#9040d0", "Teal": "#26b4b4",
    "Pink": "#f272b4", "Neutral/None": "#a0a0a0",
}

# Magic terrain overlays. These carry an empty footprint mask and cover an
# area by being placed densely, so they are drawn as a tile tint rather than
# as one marker per object.
EFFECT_COLORS = {
    21: ("Cursed Ground", "#8a8a8a"), 46: ("Magic Plains", "#e8c040"),
    222: ("Clover Field", "#7bd97b"), 223: ("Cursed Ground", "#8a8a8a"),
    224: ("Evil Fog", "#7a5c9e"), 225: ("Favorable Winds", "#9fd4ff"),
    226: ("Fiery Fields", "#ff6a40"), 227: ("Holy Ground", "#fff2a8"),
    228: ("Lucid Pools", "#45d6ff"), 229: ("Magic Clouds", "#c48cff"),
    230: ("Magic Plains", "#e8c040"), 231: ("Rocklands", "#b09070"),
}

# Purely decorative object classes — drawn as terrain shading, never markered.
SCENERY_IDS = set(range(114, 162)) | {177, 199} | set(range(200, 212))

# category key -> (label, colour, shape, marker size in tiles)
CATEGORIES = {
    "town":      ("Town",              None,      "square",   3.0),
    "hero":      ("Hero",              None,      "circle",   2.0),
    "prison":    ("Prison",            "#b0b0b0", "circle",   2.0),
    "monster":   ("Monster",           "#d81f1f", "triangle", 2.0),
    "mine":      ("Mine",              "#f2d024", "diamond",  2.2),
    "resource":  ("Resource",          "#ffe066", "square",   1.4),
    "artifact":  ("Artifact",          "#e050d0", "diamond",  1.6),
    "quest":     ("Seer / Quest",      "#30d8d8", "square",   2.0),
    "dwelling":  ("Creature dwelling", "#ff8c1a", "square",   2.2),
    "pandora":   ("Pandora / Event",   "#a060ff", "diamond",  1.8),
    "garrison":  ("Garrison",          "#8b1a1a", "square",   2.2),
    "sign":      ("Sign / Bottle",     "#ffffff", "circle",   1.2),
    "portal":    ("Portal / Gate",     "#66ccff", "circle",   1.8),
    "grail":     ("Grail",             "#ffd700", "diamond",  2.4),
    "border":    ("Border guard/gate", "#c08040", "square",   1.8),
    "boat":      ("Boat",              "#d0b080", "circle",   1.6),
    "other":     ("Other visitable",   "#cfcfcf", "circle",   1.2),
    "effect":    ("Magic terrain",     None,      "tint",     0.0),
}

_CAT_BY_ID = {}
for _ids, _cat in (
    ((98, 77), "town"), ((34, 70), "hero"), ((62,), "prison"),
    ((54, 71, 72, 73, 74, 75, 162, 163, 164), "monster"),
    ((53, 220), "mine"), ((79, 76), "resource"),
    ((5, 65, 66, 67, 68, 69, 93), "artifact"),
    ((83, 215), "quest"),
    ((17, 18, 19, 20, 216, 217, 218), "dwelling"),
    ((6, 26), "pandora"), ((33, 219), "garrison"), ((91, 59), "sign"),
    ((43, 44, 45, 103, 111), "portal"), ((36,), "grail"),
    ((9, 10, 212), "border"), ((8,), "boat"),
):
    for _i in _ids:
        _CAT_BY_ID[_i] = _cat


def categorize(o):
    """Return a category key, or None if the object is pure scenery."""
    oid = o["object_id"]
    if oid in EFFECT_COLORS:
        return "effect"
    if oid in _CAT_BY_ID:
        return _CAT_BY_ID[oid]
    if oid in SCENERY_IDS:
        return None
    return "other"


def marker_color(cat, o):
    fixed = CATEGORIES[cat][1]
    if fixed:
        return fixed
    return PLAYER_COLORS.get(o.get("owner", "Neutral/None"), "#a0a0a0")


# --------------------------------------------------------------------------
# Tile indexing
# --------------------------------------------------------------------------
def build_tile_index(m):
    """(x, y, z) -> list of {index, role, blocked, visitable}."""
    idx = {}
    size = m["size"]
    for o in m["objects"]:
        tpl = m["templates"][o["template_index"]]
        anchor = (o["x"], o["y"], o["z"])
        for dx, dy, blocked, visitable in h3m.footprint(tpl):
            tx, ty = o["x"] + dx, o["y"] + dy
            if 0 <= tx < size and 0 <= ty < size:
                key = (tx, ty, o["z"])
                idx.setdefault(key, []).append({
                    "index": o["index"],
                    "role": "anchor" if key == anchor else "footprint",
                    "blocked": blocked, "visitable": visitable})
        if not h3m.footprint(tpl):
            idx.setdefault(anchor, []).append({
                "index": o["index"], "role": "anchor",
                "blocked": False, "visitable": False})
    return idx


def build_terrain_index(m):
    """(x, y, z) -> (terrain name, river name, road name)."""
    out = {}
    for (x, y, z, t, tv, rv, rd, rt, rdd, fl) in m["terrain"]:
        out[(x, y, z)] = (
            h3m.TERRAIN[t] if t < len(h3m.TERRAIN) else str(t),
            h3m.RIVER[rv] if rv < len(h3m.RIVER) else str(rv),
            h3m.ROAD[rt] if rt < len(h3m.ROAD) else str(rt),
        )
    return out


# --------------------------------------------------------------------------
# Colour computation
# --------------------------------------------------------------------------
def _shade(hex_color, factor):
    """factor < 1 darkens, > 1 lightens."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    f = lambda v: max(0, min(255, int(v * factor)))
    return f"#{f(r):02x}{f(g):02x}{f(b):02x}"


def _blend(a, b, t):
    """Mix colour b into colour a by fraction t."""
    out = "#"
    for i in (1, 3, 5):
        va, vb = int(a[i:i+2], 16), int(b[i:i+2], 16)
        out += f"{int(va * (1 - t) + vb * t):02x}"
    return out


PASS_FREE, PASS_BLOCKED, PASS_VISITABLE = 0, 1, 2
IMPASSABLE_TERRAIN = {"Rock"}
WATER_TERRAIN = {"Water"}
PASS_COLORS = {1: "#c0392b", 2: "#d4b106"}     # blocked, visitable


def base_rows(m, z, terrain_idx, tile_idx, overlay=None):
    """overlay=None for plain terrain, "passability" for the editor-style
    red/yellow blocked-and-interactive view."""
    """Rows of "#rrggbb" strings for one map level.

    Terrain colour, darkened where an object blocks the tile and lightened
    where a road runs, so the road network stays readable.
    """
    size = m["size"]
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            terr, river, road = terrain_idx.get((x, y, z), ("Rock", "None", "None"))
            c = TERRAIN_COLORS.get(terr, UNKNOWN_TERRAIN)
            if road != "None":
                c = _shade(c, 1.35)
            elif river != "None":
                c = _shade(c, 0.75)
            if overlay == "passability":
                pv = _pass_at(m, z, x, y, terrain_idx, tile_idx)
                if pv:
                    c = _blend(c, PASS_COLORS[pv], 0.55)
                    row.append(c)
                    continue
            entries = tile_idx.get((x, y, z))
            if entries:
                for e in entries:
                    eff = EFFECT_COLORS.get(m["objects"][e["index"]]["object_id"])
                    if eff:
                        c = _blend(c, eff[1], 0.45)
                        break
                if any(e["blocked"] for e in entries):
                    c = _shade(c, 0.55)
            row.append(c)
        rows.append(row)
    return rows


def _pass_at(m, z, x, y, terrain_idx, tile_idx):
    terr = terrain_idx.get((x, y, z), ("Rock", "None", "None"))[0]
    entries = tile_idx.get((x, y, z))
    if entries:
        if any(e["visitable"] for e in entries):
            return PASS_VISITABLE
        if any(e["blocked"] for e in entries):
            return PASS_BLOCKED
    if terr in IMPASSABLE_TERRAIN:
        return PASS_BLOCKED
    return 0


def markers(m, z):
    """Marker descriptors for every non-scenery object on one level."""
    out = []
    for o in m["objects"]:
        if o["z"] != z:
            continue
        cat = categorize(o)
        if cat is None or cat == "effect":
            continue          # scenery and area tints are not markered
        label, _, shape, radius = CATEGORIES[cat]
        # place the marker on the visitable tile when there is one
        tpl = m["templates"][o["template_index"]]
        vx, vy = o["x"], o["y"]
        for dx, dy, blocked, visitable in h3m.footprint(tpl):
            if visitable:
                vx, vy = o["x"] + dx, o["y"] + dy
                break
        out.append({"x": vx, "y": vy, "category": cat, "label": label,
                    "color": marker_color(cat, o), "shape": shape,
                    "radius": radius, "index": o["index"], "name": o["name"]})
    return out


# --------------------------------------------------------------------------
# Hover text
# --------------------------------------------------------------------------
def tile_info(m, x, y, z, terrain_idx, tile_idx):
    """Human-readable lines describing one tile."""
    lines = [f"Tile ({x}, {y}, {z})  —  {'underground' if z else 'surface'}"]
    terr, river, road = terrain_idx.get((x, y, z), ("?", "None", "None"))
    bits = [terr]
    if road != "None":
        bits.append(f"{road} road")
    if river != "None":
        bits.append(f"{river} river")
    lines.append("Terrain: " + ", ".join(bits))

    entries = tile_idx.get((x, y, z), [])
    if not entries:
        lines.append("")
        lines.append("(nothing here)")
        return lines

    lines.append("")
    lines.append(f"{len(entries)} object(s):")
    for e in entries:
        o = m["objects"][e["index"]]
        flags = []
        if e["role"] == "anchor":
            flags.append("anchor")
        if e["blocked"]:
            flags.append("blocked")
        if e["visitable"]:
            flags.append("entrance")
        lines.append(f"  • {o['name']}"
                     + (f" [{', '.join(flags)}]" if flags else ""))
        summary = h3m.detail_of(o)
        if summary:
            lines.append(f"      {summary}")
        if o.get("owner"):
            lines.append(f"      owner: {o['owner']}")
        for c in h3m.object_creatures(o):
            amount = "random count of" if c.get("random_count") else f"{c['count']}x"
            lines.append(f"      {c['source']}: {amount} {c['creature']}")
        msg = (o.get("message") or "").strip()
        if msg:
            short = msg if len(msg) <= 160 else msg[:157] + "..."
            lines.append(f"      \u201c{short}\u201d")
    return lines


def legend_entries():
    return [(CATEGORIES[k][0], CATEGORIES[k][1], CATEGORIES[k][2])
            for k in CATEGORIES]


# --------------------------------------------------------------------------
# Passability
# --------------------------------------------------------------------------
# Mirrors the map editor's passability view: red where a hero cannot walk,
# yellow where a tile is blocked but interactive (a mine entrance, a chest).
def passability_grid(m, z, terrain_idx=None, tile_idx=None):
    """(width x height) grid of PASS_* values for one level."""
    size = m["size"]
    terrain_idx = terrain_idx or build_terrain_index(m)
    tile_idx = tile_idx or build_tile_index(m)
    grid = [[PASS_FREE] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            terr = terrain_idx.get((x, y, z), ("Rock", "None", "None"))[0]
            if terr in IMPASSABLE_TERRAIN:
                grid[y][x] = PASS_BLOCKED
    for (x, y, zz), entries in tile_idx.items():
        if zz != z or not (0 <= x < size and 0 <= y < size):
            continue
        blocked = any(e["blocked"] for e in entries)
        visitable = any(e["visitable"] for e in entries)
        if visitable:
            grid[y][x] = PASS_VISITABLE
        elif blocked:
            grid[y][x] = PASS_BLOCKED
    return grid


def water_grid(m, z, terrain_idx=None):
    terrain_idx = terrain_idx or build_terrain_index(m)
    size = m["size"]
    return [[terrain_idx.get((x, y, z), ("Rock",))[0] in WATER_TERRAIN
             for x in range(size)] for y in range(size)]


def walkable(grid, water, x, y, size, allow_visitable=True):
    if not (0 <= x < size and 0 <= y < size):
        return False
    if water[y][x]:
        return False
    v = grid[y][x]
    if v == PASS_BLOCKED:
        return False
    if v == PASS_VISITABLE and not allow_visitable:
        return False
    return True


def flood(grid, water, size, starts, blocked_tiles=(), limit=None):
    """8-directional flood fill, treating `blocked_tiles` as walls."""
    walls = set(blocked_tiles)
    seen = set()
    stack = [s for s in starts
             if s not in walls and walkable(grid, water, s[0], s[1], size)]
    seen.update(stack)
    while stack:
        x, y = stack.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                p = (nx, ny)
                if p in seen or p in walls:
                    continue
                if not walkable(grid, water, nx, ny, size):
                    continue
                seen.add(p)
                stack.append(p)
                if limit and len(seen) > limit:
                    return seen
    return seen
