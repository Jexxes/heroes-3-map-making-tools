"""
h3m_report.py — a single-file, self-contained HTML analysis report for a map.

Covers the same ground as the classic web map-info pages (terrain breakdown,
towns, heroes, artifacts, monsters, quests, events, restrictions, object
counts) plus an interactive map you can hover, and an optional balance
section.

Pure standard library: the map image is encoded as a PNG by hand so nothing
needs Pillow.
"""

import base64
import binascii
import html
import json
import math
import os
import statistics
import struct
import zlib
from collections import Counter, defaultdict

import h3m
import h3m_render as render
import h3m_creatures as creatures

HERO_CLASSES = ["Knight", "Cleric", "Ranger", "Druid", "Alchemist", "Wizard",
                "Demoniac", "Heretic", "Death Knight", "Necromancer",
                "Overlord", "Warlock", "Barbarian", "Battle Mage",
                "Beastmaster", "Witch", "Planeswalker", "Elementalist"]


def hero_class(hid):
    return HERO_CLASSES[hid // 8] if hid < 144 else "Campaign"


# --------------------------------------------------------------------------
# Minimal PNG writer (no Pillow needed)
# --------------------------------------------------------------------------
def encode_png(rows_rgb):
    """rows_rgb: list of rows, each a list of (r, g, b). Returns PNG bytes."""
    h = len(rows_rgb)
    w = len(rows_rgb[0]) if h else 0
    raw = bytearray()
    for row in rows_rgb:
        raw.append(0)                       # filter type 0
        for (r, g, b) in row:
            raw += bytes((r, g, b))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def hex_to_rgb(c):
    return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))


def map_png_datauri(m, z, terrain_idx, tile_idx):
    rows = render.base_rows(m, z, terrain_idx, tile_idx)
    png = encode_png([[hex_to_rgb(c) for c in row] for row in rows])
    return "data:image/png;base64," + base64.b64encode(png).decode()


# --------------------------------------------------------------------------
# Small HTML helpers
# --------------------------------------------------------------------------
def esc(v):
    return html.escape("" if v is None else str(v))


def table(headers, rows, cls="sortable", empty="Nothing of this kind on the map."):
    if not rows:
        return f'<p class="empty">{esc(empty)}</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for r in rows:
        cells = "".join(f"<td>{c if isinstance(c, Raw) else esc(c)}</td>" for c in r)
        body.append(f"<tr>{cells}</tr>")
    return (f'<div class="tablewrap"><table class="{cls}">'
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
            f"</table></div>")


class Raw(str):
    """Marks a cell as pre-built HTML."""


def pos(o):
    return f"[{o['x']},{o['y']},{o['z']}]"


def owner_chip(name):
    color = render.PLAYER_COLORS.get(name, "#8a8a95")
    return Raw(f'<span class="chip"><i style="background:{color}"></i>'
               f'{esc(name or "Neutral")}</span>')


def bar(pct, color="#5aa9e6"):
    return Raw(f'<div class="bar"><span style="width:{pct:.1f}%;'
               f'background:{color}"></span></div>'
               f'<span class="barval">{pct:.1f}%</span>')




# --------------------------------------------------------------------------
# Inline SVG charts
# --------------------------------------------------------------------------
# Drawn by hand rather than with a charting library, so the report stays a
# single file that opens with no network access.

CHART_COLORS = ["#6cc0ff", "#ffc861", "#7bd97b", "#ff8c7a", "#c48cff",
                "#45d6ff", "#ffd700", "#ff6a9f", "#9fd4ff", "#b0e57c"]


def svg_bars(pairs, width=520, bar_h=20, gap=6, color=None, unit="",
             max_items=14, colors=None):
    """Horizontal bar chart from [(label, value), ...].

    `colors` maps a label to a colour, for charts where the category already
    has a meaning (balance verdicts, player colours).
    """
    pairs = [(str(k), float(v)) for k, v in pairs if v][:max_items]
    if not pairs:
        return '<p class="empty">Nothing to chart.</p>'
    top = max(v for _k, v in pairs) or 1
    label_w, value_w = 150, 70
    plot = width - label_w - value_w
    height = len(pairs) * (bar_h + gap) + gap
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" '
           f'width="100%" height="{height}">']
    for i, (k, v) in enumerate(pairs):
        y = gap + i * (bar_h + gap)
        w = max(1, plot * v / top)
        c = (colors or {}).get(k) or color or CHART_COLORS[i % len(CHART_COLORS)]
        out.append(f'<text x="{label_w - 8}" y="{y + bar_h * 0.72}" '
                   f'text-anchor="end" class="clab">{esc(k[:22])}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{w:.1f}" '
                   f'height="{bar_h}" rx="3" fill="{c}"/>')
        shown = f"{v:,.0f}" if v >= 10 else f"{v:,.2f}".rstrip("0").rstrip(".")
        out.append(f'<text x="{label_w + w + 8:.1f}" y="{y + bar_h * 0.72}" '
                   f'class="cval">{shown}{esc(unit)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_columns(pairs, width=520, height=200, color="#6cc0ff", unit=""):
    """Vertical column chart, for ordered categories such as creature tiers."""
    pairs = [(str(k), float(v)) for k, v in pairs]
    if not pairs or not any(v for _k, v in pairs):
        return '<p class="empty">Nothing to chart.</p>'
    top = max(v for _k, v in pairs) or 1
    pad_b, pad_t, pad_l = 26, 14, 34
    plot_h = height - pad_b - pad_t
    n = len(pairs)
    slot = (width - pad_l - 8) / n
    bw = slot * 0.66
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" '
           f'width="100%" height="{height}">']
    out.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - 4}" '
               f'y2="{pad_t + plot_h}" stroke="#2c2f3d"/>')
    out.append(f'<text x="{pad_l - 6}" y="{pad_t + 8}" text-anchor="end" '
               f'class="cval">{top:,.0f}</text>')
    for i, (k, v) in enumerate(pairs):
        h = plot_h * v / top
        x = pad_l + i * slot + (slot - bw) / 2
        y = pad_t + plot_h - h
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                   f'height="{max(h, 0):.1f}" rx="2" fill="{color}"/>')
        if v:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{y - 4:.1f}" '
                       f'text-anchor="middle" class="cval">{v:,.0f}{esc(unit)}'
                       f'</text>')
        out.append(f'<text x="{x + bw / 2:.1f}" y="{height - 8}" '
                   f'text-anchor="middle" class="clab">{esc(k)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_grouped(categories, series, width=560, height=230):
    """Grouped columns: series is [(name, colour, {category: value})]."""
    if not categories or not series:
        return '<p class="empty">Nothing to chart.</p>'
    top = max((max(d.get(c, 0) for c in categories) for _n, _c, d in series),
              default=0) or 1
    pad_b, pad_t, pad_l = 42, 14, 34
    plot_h = height - pad_b - pad_t
    slot = (width - pad_l - 8) / len(categories)
    bw = slot * 0.8 / len(series)
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" '
           f'width="100%" height="{height}">']
    out.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - 4}" '
               f'y2="{pad_t + plot_h}" stroke="#2c2f3d"/>')
    for ci, cat in enumerate(categories):
        base = pad_l + ci * slot + slot * 0.1
        for si, (_name, colour, data) in enumerate(series):
            v = data.get(cat, 0)
            h = plot_h * v / top
            x = base + si * bw
            out.append(f'<rect x="{x:.1f}" y="{pad_t + plot_h - h:.1f}" '
                       f'width="{bw * 0.9:.1f}" height="{max(h, 0):.1f}" '
                       f'rx="2" fill="{colour}"><title>{esc(_name)}: '
                       f'{v:,.0f}</title></rect>')
        out.append(f'<text x="{base + slot * 0.4:.1f}" y="{height - 24}" '
                   f'text-anchor="middle" class="clab">{esc(cat[:10])}</text>')
    for si, (name, colour, _d) in enumerate(series):
        x = pad_l + si * 96
        out.append(f'<rect x="{x}" y="{height - 14}" width="9" height="9" '
                   f'rx="2" fill="{colour}"/>')
        out.append(f'<text x="{x + 13}" y="{height - 6}" class="clab">'
                   f'{esc(name)}</text>')
    out.append("</svg>")
    return "".join(out)




def svg_pie(pairs, size=230, max_items=9, hole=0.52):
    """Donut chart with a legend, for shares of a whole such as terrain."""
    pairs = [(str(k), float(v)) for k, v in pairs if v]
    if not pairs:
        return '<p class="empty">Nothing to chart.</p>'
    pairs.sort(key=lambda kv: -kv[1])
    if len(pairs) > max_items:
        rest = sum(v for _k, v in pairs[max_items:])
        pairs = pairs[:max_items] + [("other", rest)]
    total = sum(v for _k, v in pairs) or 1
    cx = cy = size / 2
    r_out, r_in = size / 2 - 4, (size / 2 - 4) * hole
    out = [f'<svg class="chart pie" viewBox="0 0 {size} {size}" '
           f'width="{size}" height="{size}">']
    angle = -math.pi / 2
    for i, (k, v) in enumerate(pairs):
        frac = v / total
        sweep = frac * 2 * math.pi
        end = angle + sweep
        colour = CHART_COLORS[i % len(CHART_COLORS)]
        if frac > 0.999:                      # a single slice is a full ring
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{(r_out + r_in) / 2:.1f}" '
                       f'fill="none" stroke="{colour}" '
                       f'stroke-width="{r_out - r_in:.1f}"/>')
        else:
            large = 1 if sweep > math.pi else 0
            x1, y1 = cx + r_out * math.cos(angle), cy + r_out * math.sin(angle)
            x2, y2 = cx + r_out * math.cos(end), cy + r_out * math.sin(end)
            x3, y3 = cx + r_in * math.cos(end), cy + r_in * math.sin(end)
            x4, y4 = cx + r_in * math.cos(angle), cy + r_in * math.sin(angle)
            out.append(
                f'<path d="M{x1:.1f},{y1:.1f} A{r_out:.1f},{r_out:.1f} 0 '
                f'{large},1 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} '
                f'A{r_in:.1f},{r_in:.1f} 0 {large},0 {x4:.1f},{y4:.1f} Z" '
                f'fill="{colour}"><title>{esc(k)}: {frac:.1%}</title></path>')
        angle = end
    out.append("</svg>")
    legend = "".join(
        f'<span class="lg"><i style="background:'
        f'{CHART_COLORS[i % len(CHART_COLORS)]}"></i>{esc(k)} '
        f'<b>{v / total:.1%}</b></span>'
        for i, (k, v) in enumerate(pairs))
    return (f'<div class="piewrap">{"".join(out)}'
            f'<div class="pielegend">{legend}</div></div>')


def svg_histogram(values, buckets, width=520, height=180, color="#6cc0ff"):
    """Counts per bucket, where buckets is [(label, lo, hi), ...]."""
    counts = []
    for label, lo, hi in buckets:
        counts.append((label, sum(1 for v in values if lo <= v < hi)))
    return svg_columns(counts, width=width, height=height, color=color)


# --------------------------------------------------------------------------
# Section builders
# --------------------------------------------------------------------------
def terrain_section(m):
    per_level = defaultdict(Counter)
    for (x, y, z, t, *_rest) in m["terrain"]:
        name = h3m.TERRAIN[t] if t < len(h3m.TERRAIN) else str(t)
        per_level[z][name] += 1
        per_level["both"][name] += 1

    blocks = []
    labels = [(0, "Ground")] + ([(1, "Underground")] if m["levels"] > 1 else [])
    labels += [("both", "Both")] if m["levels"] > 1 else []
    for key, label in labels:
        c = per_level[key]
        total = sum(c.values()) or 1
        rows = [(i + 1, n, bar(100 * v / total))
                for i, (n, v) in enumerate(c.most_common())]
        blocks.append(f'<div class="col"><h3>{label}</h3>'
                      + table(["#", "Terrain", "Share"], rows) + "</div>")

    pies = []
    for key, label in labels:
        c = per_level[key]
        if c:
            pies.append(f'<div class="col"><h3>{esc(label)}</h3>'
                        + svg_pie(c.most_common()) + "</div>")
    chart = f'<div class="cols">{"".join(pies)}</div>' if pies else ""
    return chart + f'<div class="cols">{"".join(blocks)}</div>'


def restrictions_section(m):
    allowed = set(m["allowed_heroes"])
    banned = defaultdict(list)
    for hid in range(156):
        if hid not in allowed:
            banned[hero_class(hid)].append(h3m.HEROES[hid]
                                           if hid < len(h3m.HEROES) else f"#{hid}")
    hero_rows = [(i + 1, k, ", ".join(v)) for i, (k, v) in enumerate(banned.items())]

    def missing(allowed_list, names, limit):
        s = set(allowed_list)
        return [(i + 1, f"{names[j] if j < len(names) else j} ({j})")
                for i, j in enumerate(x for x in range(limit) if x not in s)]

    art_rows = (missing(m["allowed_artifacts"], h3m.ARTIFACTS, 141)
                if m["allowed_artifacts"] else [])
    spell_rows = missing(m["allowed_spells"], h3m.SPELLS, 70) if m["allowed_spells"] else []
    skill_rows = missing(m["allowed_skills"], h3m.SEC_SKILLS, 28) if m["allowed_skills"] else []

    heroes_tbl = table(["#", "Class", "Heroes"], hero_rows,
                       empty="All heroes available.")
    arts_tbl = table(["#", "Artifact"], art_rows, empty="None disabled.")
    spells_tbl = table(["#", "Spell"], spell_rows, empty="None disabled.")
    skills_tbl = table(["#", "Skill"], skill_rows, empty="None disabled.")
    return (f"<h3>Unavailable heroes</h3>{heroes_tbl}"
            f'<div class="cols">'
            f'<div class="col"><h3>Disabled artifacts</h3>{arts_tbl}</div>'
            f'<div class="col"><h3>Disabled spells</h3>{spells_tbl}</div>'
            f'<div class="col"><h3>Disabled skills</h3>{skills_tbl}</div>'
            f"</div>")


def artifact_parents(m):
    """Every artifact instance and where it lives."""
    out = []
    for o in m["objects"]:
        oid = o["object_id"]
        if oid == 5:
            out.append((h3m.aname(o["object_subid"]), pos(o), "Map",
                        "guarded" if o.get("guards") else ""))
        elif oid in (65, 66, 67, 68, 69):
            out.append((o["name"], pos(o), "Map",
                        "guarded" if o.get("guards") else ""))
        elif oid == 93:
            out.append((f"Spell Scroll: {h3m.spname(o.get('spell_id'))}",
                        pos(o), "Map", ""))
        elif oid in (34, 70, 62):
            who = o.get("hero_name") or h3m.hname(o.get("hero_id"))
            arts = o.get("artifacts") or {}
            for slot, v in arts.items():
                if slot == "backpack":
                    for a in v:
                        out.append((h3m.aname(a), pos(o), f"Hero: {who}", "backpack"))
                else:
                    out.append((h3m.aname(v["id"]), pos(o), f"Hero: {who}", slot))
        elif oid in (6, 26):
            for a in o.get("artifacts") or []:
                out.append((h3m.aname(a), pos(o), o["name"], ""))
        elif oid == 54 and o.get("reward_artifact") is not None:
            out.append((h3m.aname(o["reward_artifact"]), pos(o),
                        f"Monster: {h3m.cname(o['object_subid'])}", ""))
        elif oid == 83 and o.get("reward", {}).get("artifact_id") is not None:
            out.append((h3m.aname(o["reward"]["artifact_id"]), pos(o),
                        "Seer's Hut reward", ""))
    out.sort(key=lambda r: r[0] or "")
    return out


def spell_sources(m):
    out = []
    for o in m["objects"]:
        oid = o["object_id"]
        if oid == 93:
            out.append((h3m.spname(o.get("spell_id")), pos(o), "Spell Scroll"))
        elif oid in (88, 89, 90):
            out.append((h3m.spname(o.get("spell_id")), pos(o), o["name"]))
        elif oid in (98, 77):
            who = o.get("town_name") or o.get("faction")
            for s in o.get("spells_obligatory", []):
                out.append((h3m.spname(s), pos(o), f"Town (always): {who}"))
        elif oid in (6, 26):
            for s in o.get("spells") or []:
                out.append((h3m.spname(s), pos(o), o["name"]))
    out.sort(key=lambda r: r[0] or "")
    return out


SECTION_IDS = ["map", "overview", "terrain", "balance", "players", "towns",
               "heroes", "monsters", "artifacts", "spells", "mines",
               "dwellings", "quests", "events", "signs", "keys",
               "restrictions", "counts"]


def build(m, path, model=None, suggestions=None, light=False, sections=None,
          exclude=None):
    """sections/exclude take section ids from SECTION_IDS; None means all."""
    terrain_idx = render.build_terrain_index(m)
    tile_idx = render.build_tile_index(m)

    # ---- map images + hover data ----
    levels = []
    for z in range(m["levels"]):
        marks = []
        for mk in render.markers(m, z):
            o = m["objects"][mk["index"]]
            marks.append({"x": mk["x"], "y": mk["y"], "c": mk["color"],
                          "s": mk["shape"], "r": mk["radius"],
                          "n": o["name"], "d": h3m.detail_of(o),
                          "o": o.get("owner", ""), "k": mk["category"]})
        levels.append({"label": "Underground" if z else "Surface",
                       "img": map_png_datauri(m, z, terrain_idx, tile_idx),
                       "marks": marks})

    def pick(*ids):
        return [o for o in m["objects"] if o["object_id"] in ids]

    # ---- overview ----
    players = [p for p in m["players"] if p["can_be_human"] or p["can_be_computer"]]
    cards = [
        ("Size", f"{m['size']}x{m['size']}" + (" + underground" if m["has_underground"] else "")),
        ("Format", m["version_name"]),
        ("Difficulty", m["difficulty"]),
        ("Players", len(players)),
        ("Objects", f"{len(m['objects']):,}"),
        ("Hero level cap", m["max_hero_level"] or "unlimited"),
        ("Victory", m["victory_condition"]["name"]),
        ("Loss", m["loss_condition"]["name"]),
    ]
    cards_html = "".join(
        f'<div class="card"><span class="k">{esc(k)}</span>'
        f'<span class="v">{esc(v)}</span></div>' for k, v in cards)

    # what the map is made of, by count
    cat_counts = Counter()
    for o in m["objects"]:
        c = render.categorize(o)
        if c and c != "effect":
            cat_counts[render.CATEGORIES[c][0]] += 1
    overview_chart = (
        '<h3>Objects by kind</h3>'
        + svg_bars(cat_counts.most_common(), width=560)
    ) if cat_counts else ""

    # ---- players ----
    fair_chart = ""
    if suggestions:
        try:
            import h3m_balance as _bal
            fair = _bal.fairness(suggestions, m)
            names = sorted(fair["per_player"])
            if names:
                series = []
                for field, colour in (("mines", "#ffc861"),
                                      ("resources", "#6cc0ff"),
                                      ("artifacts", "#c48cff"),
                                      ("dwellings", "#7bd97b")):
                    series.append((field, colour,
                                   {n: fair["per_player"][n].get(field, 0)
                                    for n in names}))
                fair_chart = ('<h3>What sits nearest each player</h3>'
                              + svg_grouped(names, series, width=560))
        except Exception:
            fair_chart = ""
    player_rows = []
    for p in players:
        who = "/".join(x for x, on in (("Human", p["can_be_human"]),
                                       ("AI", p["can_be_computer"])) if on)
        mt = p.get("main_town")
        player_rows.append((owner_chip(p["color"]), who,
                            ", ".join(p["allowed_factions"]) or "-",
                            f"[{mt['x']},{mt['y']},{mt['z']}]" if mt else "-",
                            (p.get("main_hero") or {}).get("name", "-"),
                            p["ai_tactic"]))

    # ---- towns ----
    town_rows = []
    for o in pick(98, 77):
        troops = "<br>".join(f"{a['count']}x {esc(a['creature'])}"
                             for a in o.get("army", [])) or "-"
        spells = ", ".join(h3m.spname(s) for s in o.get("spells_obligatory", []))
        town_rows.append((o.get("town_name") or "-", pos(o), owner_chip(o.get("owner")),
                          o.get("faction"), len(o.get("events", [])),
                          Raw(troops), spells or "-"))

    # ---- heroes ----
    hero_rows = []
    for o in pick(34, 70, 62):
        hid = o.get("hero_id")
        army = "<br>".join(f"{a['count']}x {esc(a['creature'])}"
                           for a in o.get("army", [])) or "-"
        hero_rows.append((o.get("hero_name") or h3m.hname(hid), pos(o),
                          owner_chip(o.get("owner")), o["name"],
                          h3m.hname(hid) if hid is not None else "-",
                          hero_class(hid) if hid is not None and hid < 156 else "-",
                          Raw(army)))

    # ---- monsters ----
    mon_rows = []
    for o in pick(54, 71, 72, 73, 74, 75, 162, 163, 164):
        cid = o["object_subid"] if o["object_id"] == 54 else None
        cm = creatures.meta(cid) if cid is not None else None
        info = ", ".join(x for x in [
            o.get("disposition"),
            "never flees" if o.get("never_flees") else None,
            "no growth" if o.get("does_not_grow") else None] if x)
        mon_rows.append((cm["name"] if cm else "Random", pos(o),
                         "random" if not o.get("count") else o["count"],
                         cm["level"] if cm else "-",
                         cm["speed"] if cm else "-",
                         f"{cm['ai_value']:,}" if cm and cm["ai_value"] else "-",
                         f"{cm['power']:,.0f}" if cm and cm["power"] else "-",
                         info, (o.get("message") or "")[:70]))

    # charts describing the monster population
    tier_counts = Counter()
    stack_powers = []
    for o in pick(54):
        cm = creatures.meta(o["object_subid"])
        if not cm:
            continue
        if cm["level"]:
            tier_counts[int(cm["level"])] += 1
        if o.get("count") and cm["power"]:
            stack_powers.append(o["count"] * cm["power"])
    monster_charts = ""
    if tier_counts:
        tiers = [(str(t), tier_counts.get(t, 0)) for t in range(1, 8)]
        monster_charts += ('<h3>Wandering monsters by tier</h3>'
                           + svg_columns(tiers, width=560, color="#ff8c7a"))
    if stack_powers:
        buckets = [("<1k", 0, 1e3), ("1–5k", 1e3, 5e3), ("5–20k", 5e3, 2e4),
                   ("20–50k", 2e4, 5e4), ("50–200k", 5e4, 2e5),
                   ("200k+", 2e5, float("inf"))]
        monster_charts += ('<h3>Guard strength spread (effective power)</h3>'
                           + svg_histogram(stack_powers, buckets, width=560))

    # ---- mines / dwellings ----
    mine_rows = [(o.get("mine_type", o["name"]), pos(o), owner_chip(o.get("owner")),
                  ", ".join(o.get("resources", [])) or "-") for o in pick(53, 220)]
    dwell_rows = []
    dwell_counts = Counter()
    for o in pick(17, 18, 19, 20, 216, 217, 218):
        produced = h3m.dwelling_name(o["object_id"], o["object_subid"],
                                     o.get("def", "")) or o["name"]
        cm = None
        who = h3m.DWELLING_CREATURE.get(o["object_subid"]) \
            if o["object_id"] == 17 else None
        if who:
            cm = creatures.meta(h3m.CREATURES.index(who))
            dwell_counts[who] += 1
        dwell_rows.append((produced, pos(o), owner_chip(o.get("owner")),
                           cm["level"] if cm else "-",
                           f"{cm['ai_value']:,}" if cm and cm["ai_value"] else "-",
                           o["name"], o["def"]))
    dwell_chart = ("<h3>Dwellings by creature</h3>"
                   + svg_bars(dwell_counts.most_common(), width=560)
                   ) if dwell_counts else ""

    # ---- quests ----
    quest_rows = []
    for o in pick(83, 215):
        q = o.get("quest", {})
        rw = o.get("reward", {})
        reward = rw.get("reward", "-")
        if reward == "Artifact":
            reward += f": {h3m.aname(rw.get('artifact_id'))}"
        elif reward == "Spell":
            reward += f": {h3m.spname(rw.get('spell_id'))}"
        elif reward == "Creatures":
            reward += f": {rw.get('count')}x {h3m.cname(rw.get('creature_id'))}"
        elif "amount" in rw:
            reward += f": {rw.get('resource','')} {rw['amount']}"
        quest_rows.append((o["name"], pos(o), q.get("mission", "-"),
                           h3m.quest_requirement(q) or "-", reward,
                           (q.get("first_visit_text") or "")[:120]))

    # ---- events / pandora ----
    ev_rows = []
    for o in pick(6, 26):
        ev_rows.append((o["name"], pos(o),
                        ", ".join(o.get("available_for", [])) or "-",
                        "yes" if o.get("remove_after_visit") else "-",
                        "<br>".join(f"{g['count']}x {esc(g['creature'])}"
                                    for g in o.get("guards", [])) or "-",
                        h3m.detail_of(o), (o.get("message") or "")[:180]))
    ev_rows = [(a, b, c, d, Raw(e), f, g) for (a, b, c, d, e, f, g) in ev_rows]

    # ---- signs, rumors, timed events ----
    sign_rows = [(o["name"], pos(o), (o.get("message") or "").strip())
                 for o in pick(91, 59) if (o.get("message") or "").strip()]
    rumor_rows = [(i + 1, r["name"], r["text"]) for i, r in enumerate(m["rumors"])]
    timed_rows = [(i + 1, e["name"], ", ".join(e["players"]) or "-",
                   e["first_occurrence"] + 1, e["repeat_after"] or "-",
                   ", ".join(f"{v:+} {k}" for k, v in e["resources"].items() if v) or "-",
                   e["message"][:200])
                  for i, e in enumerate(m["global_events"])]

    # ---- keymasters / portals ----
    key_rows = [(o["name"], o["object_subid"], pos(o)) for o in pick(9, 10, 212)]
    portal_groups = defaultdict(list)
    for o in pick(43, 44, 45, 103, 111):
        portal_groups[(o["name"], o["object_subid"])].append(pos(o))
    portal_rows = [(n, sub, len(v), ", ".join(v[:12]))
                   for (n, sub), v in sorted(portal_groups.items())]

    # ---- object counts ----
    cnt = Counter((o["object_id"], o["name"]) for o in m["objects"])
    count_rows = [(i + 1, oid, name, n) for i, ((oid, name), n)
                  in enumerate(sorted(cnt.items(), key=lambda kv: -kv[1]))]

    # ---- balance ----
    balance_html = ""
    if suggestions:
        sc = Counter(s["status"] for s in suggestions)
        chips = "".join(
            f'<div class="card"><span class="k">{esc(k)}</span>'
            f'<span class="v">{v}</span></div>'
            for k, v in sc.most_common())

        order = ["much too weak", "weak", "on curve", "strong",
                 "much too strong", "random quantity"]
        verdict_colors = {
            "much too weak": "#3b6bff", "weak": "#4bc0ff",
            "on curve": "#3fd07a", "strong": "#ffa62b",
            "much too strong": "#ff3b30", "random quantity": "#9a9aa5"}
        verdict_chart = svg_bars(
            [(k, sc.get(k, 0)) for k in order if sc.get(k)], width=560,
            colors=verdict_colors)

        # guard strength by what is guarded, from this map's own stacks
        by_reward = defaultdict(list)
        for s in suggestions:
            if s["count"]:
                by_reward[s["reward"]].append(s["current_power"])
        reward_chart = svg_bars(
            sorted(((k, statistics.median(v)) for k, v in by_reward.items()
                    if len(v) >= 2), key=lambda kv: -kv[1]),
            width=560, color="#ffc861")

        # every stack, for the live filter
        rows = [{"c": s["creature"], "x": s["x"], "y": s["y"], "z": s["z"],
                 "n": s["count"], "s": s["suggested_count"],
                 "lo": s["suggested_low"], "hi": s["suggested_high"],
                 "r": s["ratio"], "v": s["status"], "g": s["reward"],
                 "p": s["nearest_player"] or "", "d": s["distance_to_start"],
                 "cf": s.get("confidence") or ""}
                for s in suggestions]
        anchor = suggestions[0].get("map_anchor")
        note = (f'<p class="empty">Targets are relative to this map\'s own '
                f'typical guard ({anchor:,} power), scaled by what each stack '
                f'guards.</p>' if anchor else "")

        balance_html = (
            f'<div class="cards">{chips}</div>{note}'
            f'<div class="cols">'
            f'<div class="col"><h3>Verdicts</h3>{verdict_chart}</div>'
            f'<div class="col"><h3>Typical guard power by reward</h3>'
            f'{reward_chart}</div></div>'
            f'<h3>Every stack</h3>'
            f'<div class="filters">'
            f'  <label>Show stacks between'
            f'    <input id="fmin" type="range" min="0" max="400" value="0">'
            f'    <b id="fminv">0.0x</b></label>'
            f'  <label>and'
            f'    <input id="fmax" type="range" min="0" max="400" value="400">'
            f'    <b id="fmaxv">any</b></label>'
            f'  <label>of the norm</label>'
            f'  <select id="fverdict"><option value="">every verdict</option>'
            + "".join(f'<option>{esc(k)}</option>' for k in order if sc.get(k))
            + f'</select>'
            f'  <input id="fsearch" type="text" placeholder="creature or reward…">'
            f'  <span id="fcount" class="fcount"></span>'
            f'</div>'
            f'<div class="tablewrap"><table id="btable" class="sortable"><thead><tr>'
            f'<th>Creature</th><th>Position</th><th>Now</th>'
            f'<th>Suggested</th><th>Ratio</th><th>Guarding</th>'
            f'<th>Nearest player</th><th>Confidence</th><th>Verdict</th>'
            f'</tr></thead><tbody></tbody></table></div>'
            f'<script>window.BALANCE_ROWS = {json.dumps(rows)};</script>')

    want = {s.strip().lower() for s in (sections or []) if s.strip()}
    drop = {s.strip().lower() for s in (exclude or []) if s.strip()}
    section_list = [
        ("map", "Map", f'<div id="mapmount"></div>'),
        ("overview", "Overview",
         f'<div class="cards">{cards_html}</div>'
         + (f'<div class="desc">{esc(m["description"])}</div>'
            if m["description"].strip() else "")
         + overview_chart),
        ("terrain", "Terrain", terrain_section(m)),
        ("players", "Players",
         table(["Player", "Playable by", "Allowed towns", "Main town",
                "Starting hero", "AI tactic"], player_rows) + fair_chart),
        ("towns", "Towns",
         table(["Name", "Position", "Owner", "Type", "Events", "Troops",
                "Guaranteed spells"], town_rows)),
        ("heroes", "Heroes",
         table(["Name", "Position", "Owner", "Kind", "Base hero", "Class",
                "Army"], hero_rows)),
        ("monsters", "Monsters", monster_charts
         + table(["Creature", "Position", "Count", "Lvl", "Speed", "AI value",
                  "Power", "Info", "Message"], mon_rows, cls="sortable")),
        ("artifacts", "Artifacts",
         table(["Artifact", "Position", "Parent", "Note"], artifact_parents(m))),
        ("spells", "Spells",
         table(["Spell", "Position", "Source"], spell_sources(m))),
        ("mines", "Mines",
         table(["Type", "Position", "Owner", "Resources"], mine_rows)),
        ("dwellings", "Dwellings",
         table(["Produces", "Position", "Owner", "Tier", "AI value",
                "Object", "Sprite"], dwell_rows) + dwell_chart),
        ("quests", "Quests",
         table(["Giver", "Position", "Mission", "Requirement", "Reward",
                "Text"], quest_rows)),
        ("events", "Events & Pandora's Boxes",
         table(["Type", "Position", "Available for", "One visit", "Guards",
                "Contents", "Text"], ev_rows)),
        ("signs", "Signs, rumors & timed events",
         table(["Type", "Position", "Text"], sign_rows)
         + "<h3>Rumors</h3>" + table(["#", "Name", "Text"], rumor_rows)
         + "<h3>Timed events</h3>"
         + table(["#", "Name", "Players", "First day", "Repeat", "Resources",
                  "Message"], timed_rows)),
        ("keys", "Keymasters & portals",
         table(["Type", "Subid", "Position"], key_rows)
         + "<h3>Portals, gates and whirlpools</h3>"
         + table(["Type", "Group", "Count", "Positions"], portal_rows)),
        ("restrictions", "Restrictions", restrictions_section(m)),
        ("counts", "Object counts",
         table(["#", "ID", "Name", "Count"], count_rows, cls="sortable")),
    ]
    if balance_html:
        section_list.insert(3, ("balance", "Balance", balance_html))

    if want or drop:
        chosen = [s for s in section_list
                  if (not want or s[0] in want) and s[0] not in drop]
        section_list = chosen or section_list
    sections = section_list
    nav = "".join(f'<a href="#{sid}">{esc(title)}</a>' for sid, title, _ in sections)
    body = "".join(
        f'<section id="{sid}"><h2>{esc(title)}</h2>{content}</section>'
        for sid, title, content in sections)

    legend = "".join(
        f'<span class="lg"><i style="background:{c or "#888"}"></i>{esc(lbl)}</span>'
        for lbl, c, _s in render.legend_entries() if lbl != "Magic terrain")

    data = json.dumps({"levels": levels, "size": m["size"]})
    title = m["name"] or os.path.basename(path)

    return HTML_TEMPLATE.format(title=esc(title), nav=nav, body=body,
                                data=data, legend=legend,
                                subtitle=esc(f"{m['size']}x{m['size']} · "
                                             f"{m['version_name']} · "
                                             f"{len(m['objects']):,} objects"))


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — map analysis</title>
<style>
:root {{
  --bg:#12131a; --panel:#1a1c25; --panel2:#20222d; --line:#2c2f3d;
  --fg:#e8e9ef; --dim:#9297ab; --accent:#6cc0ff; --accent2:#ffc861;
}}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif }}
header {{ padding:28px 32px 18px; border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,#191b24,#12131a) }}
header h1 {{ margin:0; font-size:26px; letter-spacing:-.4px }}
header p {{ margin:6px 0 0; color:var(--dim); font-size:14px }}
nav {{ position:sticky; top:0; z-index:20; display:flex; flex-wrap:wrap; gap:2px;
  padding:8px 24px; background:rgba(18,19,26,.94); backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line) }}
nav a {{ color:var(--dim); text-decoration:none; font-size:13px;
  padding:6px 11px; border-radius:7px }}
nav a:hover {{ color:var(--fg); background:var(--panel2) }}
main {{ padding:8px 32px 80px; max-width:1500px; margin:0 auto }}
section {{ margin:30px 0 }}
h2 {{ font-size:19px; margin:0 0 14px; padding-bottom:8px;
  border-bottom:1px solid var(--line) }}
h3 {{ font-size:14px; color:var(--accent2); margin:20px 0 8px;
  text-transform:uppercase; letter-spacing:.6px }}
.cards {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:14px }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:11px 15px; min-width:130px }}
.card .k {{ display:block; color:var(--dim); font-size:11px;
  text-transform:uppercase; letter-spacing:.7px }}
.card .v {{ display:block; font-size:17px; margin-top:3px }}
.desc {{ background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--accent);
  border-radius:8px; padding:14px 18px; color:#c9cddc; white-space:pre-wrap }}
.tablewrap {{ overflow:auto; border:1px solid var(--line); border-radius:10px;
  max-height:620px }}
table {{ border-collapse:collapse; width:100%; font-size:13.5px }}
th {{ position:sticky; top:0; background:var(--panel2); text-align:left;
  padding:9px 12px; font-weight:600; border-bottom:1px solid var(--line);
  white-space:nowrap; z-index:2 }}
table.sortable th {{ cursor:pointer; user-select:none }}
table.sortable th:hover {{ color:var(--accent) }}
table.sortable th::after {{ content:"\2195"; opacity:.25; margin-left:6px;
  font-size:11px }}
table.sortable th.asc::after {{ content:"\2191"; opacity:1;
  color:var(--accent) }}
table.sortable th.desc::after {{ content:"\2193"; opacity:1;
  color:var(--accent) }}
.piewrap {{ display:flex; gap:14px; align-items:center; flex-wrap:wrap }}
.pielegend {{ display:flex; flex-direction:column; gap:3px }}
.pielegend .lg b {{ color:var(--fg) }}
td {{ padding:8px 12px; border-bottom:1px solid #23252f; vertical-align:top }}
tr:nth-child(even) td {{ background:#171922 }}
tr:hover td {{ background:#232838 }}
.empty {{ color:var(--dim); font-style:italic; margin:4px 0 }}
.chip {{ display:inline-flex; align-items:center; gap:6px; white-space:nowrap }}
.chip i {{ width:10px; height:10px; border-radius:3px; display:inline-block;
  border:1px solid rgba(0,0,0,.5) }}
.bar {{ display:inline-block; width:150px; height:9px; background:#262a36;
  border-radius:5px; overflow:hidden; vertical-align:middle }}
.bar span {{ display:block; height:100%; border-radius:5px }}
.barval {{ margin-left:9px; color:var(--dim); font-variant-numeric:tabular-nums }}
.cols {{ display:flex; gap:18px; flex-wrap:wrap }}
.chart {{ margin:6px 0 14px; overflow:visible }}
.chart .clab {{ fill:var(--dim); font-size:11px }}
.chart .cval {{ fill:var(--fg); font-size:11px }}
.filters {{ display:flex; flex-wrap:wrap; gap:14px; align-items:center;
  background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:12px 16px; margin-bottom:10px; font-size:13.5px }}
.filters label {{ display:flex; align-items:center; gap:8px; color:var(--dim) }}
.filters b {{ color:var(--accent); font-variant-numeric:tabular-nums;
  min-width:44px }}
.filters input[type=range] {{ width:150px; accent-color:var(--accent) }}
.filters input[type=text], .filters select {{ background:#15151a;
  color:var(--fg); border:1px solid var(--line); border-radius:6px;
  padding:5px 8px }}
.fcount {{ color:var(--accent2); margin-left:auto }}
.v-much.too, .v-much {{ color:#ff6a5a }}
.col {{ flex:1; min-width:280px }}
/* map */
#mapmount {{ display:flex; gap:18px; flex-wrap:wrap; align-items:flex-start }}
#stage {{ position:relative; border:1px solid var(--line); border-radius:10px;
  overflow:hidden; background:#0c0d12; line-height:0 }}
#stage img {{ image-rendering:pixelated; display:block }}
#stage svg {{ position:absolute; inset:0 }}
.side {{ flex:1 1 300px; min-width:260px; max-width:420px; position:sticky; top:60px }}
.mapbtns {{ display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap }}
button {{ background:var(--panel2); color:var(--fg); border:1px solid var(--line);
  padding:7px 13px; border-radius:8px; cursor:pointer; font-size:13px }}
button:hover {{ border-color:var(--accent); color:var(--accent) }}
button.on {{ background:var(--accent); color:#0d1017; border-color:var(--accent) }}
#tip {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; min-height:120px; font-size:13.5px; line-height:1.6 }}
#tip .t {{ color:var(--accent); font-weight:600 }}
#tip .s {{ color:var(--dim) }}
.legend {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:12px; line-height:1.4 }}
.lg {{ display:inline-flex; align-items:center; gap:6px; font-size:12px;
  color:var(--dim) }}
.lg i {{ width:11px; height:11px; border-radius:3px; border:1px solid #000 }}
footer {{ color:var(--dim); font-size:12.5px; padding:24px 32px;
  border-top:1px solid var(--line) }}
.printbtn {{ background:var(--panel2); color:var(--fg);
  border:1px solid var(--line); border-radius:8px; padding:6px 12px;
  cursor:pointer; font-size:13px; margin-left:14px }}
.printbtn:hover {{ border-color:var(--accent); color:var(--accent) }}

/* ---- printing / save as PDF ----
   The screen theme is dark, which wastes ink and prints poorly, so print
   flips the palette. Because every colour comes from a custom property,
   redefining them here recolours the SVG charts too. */
@media print {{
  :root {{
    --bg:#ffffff; --panel:#ffffff; --panel2:#f1f2f6; --line:#c9ccd6;
    --fg:#14161c; --dim:#5b6070; --accent:#0d5f9e; --accent2:#8a6300;
  }}
  body {{ background:#fff; color:#14161c; font-size:10.5pt }}
  nav, .filters, .printbtn, .mapbtns {{ display:none !important }}
  header {{ background:#fff; border-bottom:2px solid #14161c;
    padding:0 0 10px }}
  main {{ padding:0; max-width:none }}
  section {{ margin:14px 0; break-inside:auto }}
  h2 {{ break-after:avoid; page-break-after:avoid }}
  h3 {{ break-after:avoid; page-break-after:avoid }}
  /* on screen the tables scroll inside a fixed height; on paper they must
     print in full */
  .tablewrap {{ max-height:none !important; overflow:visible !important;
    border:1px solid #c9ccd6 }}
  table {{ font-size:8.5pt; width:100% }}
  thead {{ display:table-header-group }}   /* repeat headers across pages */
  tr {{ break-inside:avoid; page-break-inside:avoid }}
  th {{ position:static; background:#f1f2f6; color:#14161c;
    border-bottom:1px solid #c9ccd6 }}
  td {{ border-bottom:1px solid #e4e6ec }}
  tr:nth-child(even) td {{ background:#f7f8fb }}
  tr:hover td {{ background:transparent }}
  .card, .desc {{ background:#fff; border:1px solid #c9ccd6 }}
  .chart, .piewrap {{ break-inside:avoid; page-break-inside:avoid }}
  #stage {{ border:1px solid #c9ccd6 }}
  #stage svg {{ position:absolute }}
  .side {{ display:none }}                 /* the hover panel means nothing on paper */
  #mapmount {{ justify-content:center }}
  a {{ color:#0d5f9e; text-decoration:none }}
  footer {{ border-top:1px solid #c9ccd6; padding:12px 0 0 }}
}}
@page {{ size:A4; margin:14mm 12mm }}
.printbtn {{ position:fixed; right:18px; bottom:18px; z-index:50;
  background:var(--accent); color:#0d1017; border:none; border-radius:9px;
  padding:10px 16px; font-size:13.5px; cursor:pointer;
  box-shadow:0 4px 14px rgba(0,0,0,.4) }}
.printbtn:hover {{ filter:brightness(1.1) }}

/* ---- print / PDF ----------------------------------------------------
   The screen view is dark and uses scrolling panes; neither survives on
   paper. For print the palette flips to ink-on-white, every scrollable
   table is unclipped so nothing is silently cut off, and the interactive
   controls are hidden because they cannot be used on a page. */
@media print {{
  @page {{ margin:14mm 12mm; }}
  :root {{
    --bg:#ffffff; --panel:#ffffff; --panel2:#f2f3f7; --line:#c8ccd8;
    --fg:#14161c; --dim:#5b6273; --accent:#1c4f80; --accent2:#7a5a12;
  }}
  body {{ background:#fff; color:#14161c; font-size:10.5pt }}
  header {{ background:#fff; border-bottom:2px solid #14161c;
    padding:0 0 8px; margin-bottom:10px }}
  header h1 {{ font-size:19pt }}
  nav, .filters, .mapbtns, .noprint {{ display:none !important }}
  main {{ padding:0; max-width:none }}
  section {{ break-inside:auto; margin:0 0 14px }}
  h2 {{ break-after:avoid; page-break-after:avoid; font-size:13pt;
    border-bottom:1px solid #14161c }}
  h3 {{ break-after:avoid; page-break-after:avoid; color:#7a5a12 }}
  /* scrollable on screen, complete on paper */
  .tablewrap {{ max-height:none !important; overflow:visible !important;
    border:1px solid #c8ccd8 }}
  table {{ font-size:8.5pt }}
  thead {{ display:table-header-group }}
  tr {{ break-inside:avoid; page-break-inside:avoid }}
  th {{ position:static; background:#f2f3f7; color:#14161c;
    border-bottom:1px solid #14161c }}
  td {{ border-bottom:1px solid #e3e6ee }}
  tr:nth-child(even) td {{ background:#f7f8fb }}
  table.sortable th {{ cursor:auto }}
  table.sortable th::after {{ content:"" }}
  .card {{ border:1px solid #c8ccd8; break-inside:avoid }}
  .card .v {{ color:#14161c }}
  .desc {{ background:#f7f8fb; color:#14161c; break-inside:avoid }}
  .chart, .piewrap, .cards {{ break-inside:avoid; page-break-inside:avoid }}
  .chart .cval {{ fill:#14161c }}
  .chart .clab {{ fill:#5b6273 }}
  .bar {{ background:#e3e6ee; border:1px solid #c8ccd8 }}
  #stage {{ border:1px solid #c8ccd8; break-inside:avoid }}
  #stage svg {{ position:absolute }}
  .side {{ display:none }}
  footer {{ border-top:1px solid #c8ccd8; color:#5b6273; padding:8px 0 0 }}
  a {{ color:#1c4f80; text-decoration:none }}
}}

</style></head><body>
<header><h1>{title}</h1>
<p>{subtitle}
<button class="printbtn" onclick="window.print()">Save as PDF</button></p>
</header>
<nav>{nav}</nav>
<main>{body}</main>
<button class="printbtn noprint" onclick="preparePrint()">Save as PDF</button>
<footer>Generated by h3m_report.py. Positions are [x,y,z]; z=0 is the surface.
Multi-tile objects are anchored at their bottom-right tile.</footer>
<script>
const DATA = {data};
let lvl = 0, scale = 4;
const mount = document.getElementById('mapmount');

function render() {{
  const L = DATA.levels[lvl], n = DATA.size, px = n * scale;
  const marks = L.marks.map(m => {{
    const cx = (m.x + .5) * scale, cy = (m.y + .5) * scale;
    const r = Math.max(1.6, m.r * scale / 5);
    const st = `fill:${{m.c}};stroke:#000;stroke-width:.7`;
    if (m.s === 'circle')
      return `<circle cx="${{cx}}" cy="${{cy}}" r="${{r}}" style="${{st}}"/>`;
    if (m.s === 'square')
      return `<rect x="${{cx-r}}" y="${{cy-r}}" width="${{2*r}}" height="${{2*r}}" style="${{st}}"/>`;
    if (m.s === 'diamond')
      return `<polygon points="${{cx}},${{cy-r}} ${{cx+r}},${{cy}} ${{cx}},${{cy+r}} ${{cx-r}},${{cy}}" style="${{st}}"/>`;
    return `<polygon points="${{cx}},${{cy-r}} ${{cx+r}},${{cy+r}} ${{cx-r}},${{cy+r}}" style="${{st}}"/>`;
  }}).join('');
  mount.innerHTML = `
    <div style="width:${{px}}px;flex:0 0 auto">
      <div class="mapbtns">
        ${{DATA.levels.map((l,i)=>`<button data-lv="${{i}}" class="${{i===lvl?'on':''}}">${{l.label}}</button>`).join('')}}
        <button data-z="-1">&minus;</button><button data-z="1">+</button>
      </div>
      <div id="stage" style="width:${{px}}px;height:${{px}}px">
        <img src="${{L.img}}" width="${{px}}" height="${{px}}">
        <svg width="${{px}}" height="${{px}}" viewBox="0 0 ${{px}} ${{px}}">${{marks}}</svg>
      </div>
      <div class="legend">{legend}</div>
    </div>
    <div class="side"><div id="tip"><span class="s">Hover the map.</span></div></div>`;

  mount.querySelectorAll('[data-lv]').forEach(b =>
    b.onclick = () => {{ lvl = +b.dataset.lv; render(); }});
  mount.querySelectorAll('[data-z]').forEach(b =>
    b.onclick = () => {{ scale = Math.max(2, Math.min(12, scale + (+b.dataset.z))); render(); }});

  const stage = document.getElementById('stage'), tip = document.getElementById('tip');
  stage.onmousemove = e => {{
    const rect = stage.getBoundingClientRect();
    const tx = Math.floor((e.clientX - rect.left) / scale);
    const ty = Math.floor((e.clientY - rect.top) / scale);
    const hits = L.marks.filter(m => m.x === tx && m.y === ty);
    let h = `<span class="t">Tile ${{tx}}, ${{ty}}, ${{lvl}}</span>`;
    if (!hits.length) h += `<br><span class="s">nothing marked here</span>`;
    for (const m of hits) {{
      h += `<br><b>${{m.n}}</b>`;
      if (m.d) h += `<br><span class="s">${{m.d}}</span>`;
      if (m.o) h += `<br><span class="s">owner: ${{m.o}}</span>`;
    }}
    tip.innerHTML = h;
  }};
}}
render();

// Printing needs the whole document laid out: the balance table is capped at
// 600 rows on screen for responsiveness, so lift the cap first.
window.PRINT_ALL = false;
function preparePrint() {{
  window.PRINT_ALL = true;
  if (window.applyBalanceFilter) window.applyBalanceFilter();
  window.setTimeout(() => {{
    window.print();
    window.PRINT_ALL = false;
    if (window.applyBalanceFilter) window.applyBalanceFilter();
  }}, 120);
}}

// live filter over the balance table
(function () {{
  const rows = window.BALANCE_ROWS;
  if (!rows) return;
  const tb = document.querySelector('#btable tbody');
  const fmin = document.getElementById('fmin');
  const fmax = document.getElementById('fmax');
  const fminv = document.getElementById('fminv');
  const fmaxv = document.getElementById('fmaxv');
  const fverdict = document.getElementById('fverdict');
  const fsearch = document.getElementById('fsearch');
  const fcount = document.getElementById('fcount');
  const COLOURS = {{
    'much too weak': '#3b6bff', 'weak': '#4bc0ff', 'on curve': '#3fd07a',
    'strong': '#ffa62b', 'much too strong': '#ff3b30',
    'random quantity': '#9a9aa5'
  }};
  // slider positions are tenths of the norm, so 0..400 covers 0x to 40x
  const val = s => s / 10;

  function apply() {{
    const lo = val(+fmin.value), hi = val(+fmax.value);
    const verdict = fverdict.value;
    const needle = fsearch.value.trim().toLowerCase();
    fminv.textContent = lo.toFixed(1) + 'x';
    fmaxv.textContent = hi >= 40 ? 'any' : hi.toFixed(1) + 'x';
    const out = [];
    let shown = 0;
    for (const r of rows) {{
      const ratio = r.r === null ? null : r.r;
      if (ratio !== null && (ratio < lo || (hi < 40 && ratio > hi))) continue;
      if (ratio === null && lo > 0) continue;
      if (verdict && r.v !== verdict) continue;
      if (needle && !(r.c.toLowerCase().includes(needle) ||
                      r.g.toLowerCase().includes(needle))) continue;
      shown++;
      if (window.PRINT_ALL || out.length < 600) {{
        out.push('<tr><td>' + r.c + '</td><td>[' + r.x + ',' + r.y + ',' +
          r.z + ']</td><td>' + (r.n || 'random') + '</td><td>' + r.lo +
          '\u2013' + r.hi + '</td><td>' + (r.r === null ? '—' : r.r + 'x') +
          '</td><td>' + r.g + '</td><td>' + r.p + '</td><td>' + r.cf +
          '</td><td style="color:' + (COLOURS[r.v] || '#cfcfcf') + '">' +
          r.v + '</td></tr>');
      }}
    }}
    tb.innerHTML = out.join('');
    fcount.textContent = shown + ' of ' + rows.length + ' stacks' +
      (shown > 600 ? ' (first 600 shown)' : '');
  }}
  [fmin, fmax].forEach(el => el.addEventListener('input', () => {{
    if (+fmin.value > +fmax.value) {{
      if (el === fmin) fmax.value = fmin.value; else fmin.value = fmax.value;
    }}
    apply();
  }}));
  window.applyBalanceFilter = apply;
  fverdict.addEventListener('change', apply);
  fsearch.addEventListener('input', apply);
  apply();
}})();

// click-to-sort, on every table
document.querySelectorAll('table.sortable').forEach(tbl => {{
  const heads = [...tbl.tHead.rows[0].cells];
  heads.forEach((th, i) => {{
    th.addEventListener('click', () => {{
      const asc = !th.classList.contains('asc');
      heads.forEach(h => h.classList.remove('asc', 'desc'));
      th.classList.add(asc ? 'asc' : 'desc');
      const tb = tbl.tBodies[0];
      const rows = [...tb.rows];
      const key = cell => {{
        const t = (cell ? cell.innerText : '').trim();
        // "[12,34,0]" sorts by x then y, not as text
        const c = t.match(/^\[(\d+),(\d+),(\d+)\]$/);
        if (c) return +c[3] * 1e8 + +c[1] * 1e4 + +c[2];
        const n = parseFloat(t.replace(/[,%x]/g, ''));
        if (!isNaN(n) && /^[-\d.,%x\s]+$/.test(t)) return n;
        return t.toLowerCase();
      }};
      // In a numeric column, cells with no value ("-", "—") stay at the
      // bottom whichever way the column is sorted, so reversing the order
      // never fills the top of the table with blanks.
      const keyed = rows.map(r => [key(r.cells[i]), r]);
      const numeric = keyed.filter(k => typeof k[0] === 'number');
      const blank = keyed.filter(k => typeof k[0] !== 'number' &&
                                      /^[-—–\s]*$/.test(String(k[0])));
      const textual = keyed.filter(k => typeof k[0] !== 'number' &&
                                        !/^[-—–\s]*$/.test(String(k[0])));
      let ordered;
      if (numeric.length >= textual.length) {{
        numeric.sort((a, b) => a[0] - b[0]);
        if (!asc) numeric.reverse();
        textual.sort((a, b) => String(a[0]).localeCompare(String(b[0])));
        ordered = numeric.concat(textual, blank);
      }} else {{
        keyed.sort((a, b) => String(a[0]).localeCompare(String(b[0])));
        if (!asc) keyed.reverse();
        ordered = keyed;
      }}
      ordered.forEach(k => tb.appendChild(k[1]));
    }});
  }});
}});
</script></body></html>
"""




# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
# Turning HTML into PDF needs a browser engine, so rather than add a rendering
# dependency the report drives a browser that is already installed. Every
# desktop has one, and the same file can always be printed by hand with
# Ctrl+P > Save as PDF, which is what the button in the report does.

BROWSER_CANDIDATES = [
    # Windows
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

BROWSER_COMMANDS = ["google-chrome", "google-chrome-stable", "chromium",
                    "chromium-browser", "microsoft-edge", "msedge", "chrome"]


class PDFError(Exception):
    pass


def find_browser():
    """A Chrome-family browser able to print to PDF, or None."""
    import shutil
    for cmd in BROWSER_COMMANDS:
        found = shutil.which(cmd)
        if found:
            return found
    for path in BROWSER_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def html_to_pdf(html_path, pdf_path, browser=None, timeout=180):
    """Render an existing report to PDF using an installed browser."""
    import subprocess
    import tempfile

    browser = browser or find_browser()
    if not browser:
        raise PDFError(
            "No Chrome, Chromium or Edge was found to render the PDF.\n"
            "Open the HTML report in any browser and use Ctrl+P > "
            "Save as PDF instead — the report carries a print stylesheet, "
            "so it lays out properly on paper.")

    url = "file://" + os.path.abspath(html_path).replace(os.sep, "/")
    if not url.startswith("file:///"):
        url = url.replace("file://", "file:///", 1)

    with tempfile.TemporaryDirectory() as profile:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
               f"--user-data-dir={profile}",
               "--no-pdf-header-footer",
               "--virtual-time-budget=15000",
               f"--print-to-pdf={os.path.abspath(pdf_path)}", url]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise PDFError("The browser took too long to render the PDF.")
        except OSError as exc:
            raise PDFError(f"Could not start {browser}: {exc}")

    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 1000:
        # older builds spell the flag differently
        detail = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        raise PDFError("The browser did not produce a PDF.\n"
                       + (detail or "No output from the browser.")
                       + "\n\nOpen the HTML report and use Ctrl+P > "
                         "Save as PDF instead.")
    return pdf_path


def write_pdf(m, path, out, model=None, suggestions=None, keep_html=None):
    """Build the report and render it straight to PDF."""
    import tempfile
    html_path = keep_html or os.path.join(
        tempfile.mkdtemp(), os.path.basename(out).replace(".pdf", ".html"))
    write(m, path, html_path, model, suggestions)
    return html_to_pdf(html_path, out)




# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
# The report is printed by a browser rather than drawn again in a PDF library:
# the same HTML, the same SVG charts, no extra dependency, and the print
# stylesheet already recolours everything for paper. Any Chromium-based
# browser can do this from the command line.

BROWSER_CANDIDATES = [
    # Windows
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

BROWSER_COMMANDS = ["google-chrome", "google-chrome-stable", "chromium",
                    "chromium-browser", "microsoft-edge", "msedge", "chrome"]


def find_browser():
    """A Chromium-based browser able to print to PDF, or None."""
    import shutil
    for cmd in BROWSER_COMMANDS:
        found = shutil.which(cmd)
        if found:
            return found
    for path in BROWSER_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class PdfUnavailable(RuntimeError):
    pass


def write_pdf(html_path, pdf_path, browser=None, timeout=180):
    """Print an existing report to PDF using an installed browser."""
    import subprocess
    import tempfile

    exe = browser or find_browser()
    if not exe:
        raise PdfUnavailable(
            "No Chromium-based browser found to print with.\n"
            "Install Chrome or Edge, or open the HTML report and use your "
            "browser's own Print \u2192 Save as PDF, which produces the same "
            "document.")
    url = "file://" + os.path.abspath(html_path).replace("\\", "/")
    if not url.startswith("file:///"):
        url = url.replace("file://", "file:///", 1)
    with tempfile.TemporaryDirectory() as profile:
        cmd = [exe, "--headless", "--disable-gpu", "--no-sandbox",
               f"--user-data-dir={profile}",
               "--no-pdf-header-footer",
               f"--print-to-pdf={os.path.abspath(pdf_path)}", url]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 1000:
        detail = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        raise PdfUnavailable(
            "The browser did not produce a PDF.\n"
            "Open the HTML report and use Print \u2192 Save as PDF instead."
            + (f"\n\n{detail}" if detail.strip() else ""))
    return pdf_path


def build_pdf(m, path, pdf_path, suggestions=None, keep_html=None,
              sections=None, exclude=None):
    """Build the report and print it, leaving the HTML behind if asked."""
    import tempfile
    html_path = keep_html or os.path.join(
        tempfile.mkdtemp(), os.path.basename(pdf_path) + ".html")
    write(m, path, html_path, suggestions=suggestions, sections=sections,
          exclude=exclude)
    write_pdf(html_path, pdf_path)
    return pdf_path


def write(m, path, out, model=None, suggestions=None, sections=None,
          exclude=None):
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(m, path, model, suggestions, sections=sections,
                      exclude=exclude))
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Build an HTML analysis report for a .h3m map, and "
                    "optionally print it to PDF.")
    ap.add_argument("map", nargs="?")
    ap.add_argument("-o", "--out", help="output .html (default: beside the map)")
    ap.add_argument("--reference", nargs="*",
                    help="reference maps, to add a balance section")
    ap.add_argument("--pdf", metavar="OUT.pdf",
                    help="also print the report to PDF with an installed "
                         "Chrome, Chromium or Edge")
    ap.add_argument("--sections",
                    help="comma-separated section ids to keep, e.g. "
                         "map,overview,terrain,balance")
    ap.add_argument("--exclude", help="comma-separated section ids to drop")
    ap.add_argument("--list-sections", action="store_true",
                    help="list the available section ids and exit")
    args = ap.parse_args()

    if args.list_sections:
        print(" ".join(SECTION_IDS))
        return
    if not args.map:
        ap.error("a map is required")

    split = lambda s: [x.strip() for x in s.split(",")] if s else None

    m = h3m.parse_file(args.map)
    sug = None
    if args.reference:
        import h3m_balance
        model = h3m_balance.build_model(args.reference)
        sug = h3m_balance.suggest(m, model, args.map)

    out = args.out or os.path.splitext(args.map)[0] + "_report.html"
    write(m, args.map, out, suggestions=sug, sections=split(args.sections),
          exclude=split(args.exclude))
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")

    if args.pdf:
        try:
            write_pdf(out, args.pdf)
            print(f"wrote {args.pdf} "
                  f"({os.path.getsize(args.pdf) / 1e6:.1f} MB)")
        except PdfUnavailable as exc:
            print(f"\nCould not make the PDF automatically:\n{exc}")


if __name__ == "__main__":
    main()
