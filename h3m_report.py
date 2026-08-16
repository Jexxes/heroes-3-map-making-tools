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
import os
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


def table(headers, rows, cls="", empty="Nothing of this kind on the map."):
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
    return f'<div class="cols">{"".join(blocks)}</div>'


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


def build(m, path, model=None, suggestions=None, light=False):
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

    # ---- players ----
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

    # ---- mines / dwellings ----
    mine_rows = [(o.get("mine_type", o["name"]), pos(o), owner_chip(o.get("owner")),
                  ", ".join(o.get("resources", [])) or "-") for o in pick(53, 220)]
    dwell_rows = [(o["name"], pos(o), owner_chip(o.get("owner")),
                   o["def"]) for o in pick(17, 18, 19, 20, 216, 217, 218)]

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
        off = [s for s in suggestions
               if s["status"] in ("much too strong", "much too weak")]
        off.sort(key=lambda s: -(s["ratio"] or 0))
        rows = [(s["creature"], f"[{s['x']},{s['y']},{s['z']}]", s["count"],
                 f"{s['suggested_low']}–{s['suggested_high']}",
                 s["ratio"], s["reward"], s["distance_to_start"],
                 s["nearest_player"], s["status"])
                for s in off[:60]]
        anchor = suggestions[0].get("map_anchor")
        note = (f'<p class="empty">Targets are relative to this map\'s own '
                f'typical guard ({anchor:,} power), scaled by what each stack '
                f'guards. Reference maps of the same size differ by up to 50x '
                f'in stack size, so no absolute scale is imposed.</p>'
                if anchor else "")
        balance_html = (f'<div class="cards">{chips}</div>' + note
                        + table(["Creature", "Position", "Now",
                                 "Suggested range", "Ratio", "Guarding",
                                 "Dist", "Nearest player", "Verdict"], rows,
                                empty="Every stack sits on the curve."))

    sections = [
        ("map", "Map", f'<div id="mapmount"></div>'),
        ("overview", "Overview",
         f'<div class="cards">{cards_html}</div>'
         + (f'<div class="desc">{esc(m["description"])}</div>'
            if m["description"].strip() else "")),
        ("terrain", "Terrain", terrain_section(m)),
        ("players", "Players",
         table(["Player", "Playable by", "Allowed towns", "Main town",
                "Starting hero", "AI tactic"], player_rows)),
        ("towns", "Towns",
         table(["Name", "Position", "Owner", "Type", "Events", "Troops",
                "Guaranteed spells"], town_rows)),
        ("heroes", "Heroes",
         table(["Name", "Position", "Owner", "Kind", "Base hero", "Class",
                "Army"], hero_rows)),
        ("monsters", "Monsters",
         table(["Creature", "Position", "Count", "Lvl", "Speed", "AI value",
                "Power", "Info", "Message"], mon_rows, cls="sortable")),
        ("artifacts", "Artifacts",
         table(["Artifact", "Position", "Parent", "Note"], artifact_parents(m))),
        ("spells", "Spells",
         table(["Spell", "Position", "Source"], spell_sources(m))),
        ("mines", "Mines",
         table(["Type", "Position", "Owner", "Resources"], mine_rows)),
        ("dwellings", "Dwellings",
         table(["Type", "Position", "Owner", "Sprite"], dwell_rows)),
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
        sections.insert(3, ("balance", "Balance", balance_html))

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


HTML_TEMPLATE = """<!doctype html>
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
</style></head><body>
<header><h1>{title}</h1><p>{subtitle}</p></header>
<nav>{nav}</nav>
<main>{body}</main>
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

// click-to-sort on numeric-ish tables
document.querySelectorAll('table.sortable th').forEach((th, i) => {{
  th.style.cursor = 'pointer';
  let asc = false;
  th.onclick = () => {{
    const tb = th.closest('table').tBodies[0];
    const rows = [...tb.rows];
    rows.sort((a, b) => {{
      const x = a.cells[i].innerText.replace(/,/g, ''), y = b.cells[i].innerText.replace(/,/g, '');
      const nx = parseFloat(x), ny = parseFloat(y);
      const both = !isNaN(nx) && !isNaN(ny);
      return (both ? nx - ny : x.localeCompare(y)) * (asc ? 1 : -1);
    }});
    asc = !asc;
    rows.forEach(r => tb.appendChild(r));
  }};
}});
</script></body></html>
"""


def write(m, path, out, model=None, suggestions=None):
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(m, path, model, suggestions))
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Build an HTML analysis report for a .h3m map")
    ap.add_argument("map")
    ap.add_argument("-o", "--out", help="output .html (default: alongside the map)")
    ap.add_argument("--reference", nargs="*",
                    help="reference maps to add a balance section")
    args = ap.parse_args()

    m = h3m.parse_file(args.map)
    sug = None
    if args.reference:
        import h3m_balance
        model = h3m_balance.build_model(args.reference)
        sug = h3m_balance.suggest(m, model, args.map)
    out = args.out or os.path.splitext(args.map)[0] + "_report.html"
    write(m, args.map, out, suggestions=sug)
    print(f"wrote {out} ({os.path.getsize(out)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
