# h3m-toolkit

Read, analyse, balance and edit **Heroes of Might & Magic III** map files
(`.h3m`) — from Python or from a desktop GUI.

Pure Python 3.8+, standard library only. No packages to install.

```bash
python3 h3m_viewer.py MyMap.h3m     # inspect a map
python3 h3m_editor.py MyMap.h3m     # edit a map
python3 h3m.py MyMap.h3m            # command-line summary
```

---

## What it does

- **Parses** RoE, Armageddon's Blade and Shadow of Death maps completely:
  terrain, every object with its true multi-tile footprint, heroes, towns,
  quests, events, restrictions.
- **Draws** the map with hover-anything inspection, plus grid, coordinate ruler
  and a passability overlay like the official editor's.
- **Analyses** balance against a corpus of reference maps you supply, using the
  game's own AI Values for creature strength.
- **Edits** safely: text, creature stacks, owners, counts, object removal —
  queued, undoable, and verified before anything is written.
- **Exports** to CSV, JSON, Markdown, and a self-contained interactive HTML
  report.

| | |
|---|---|
| **User guide** | this file |
| **Technical documentation** | [`DOCUMENTATION.md`](DOCUMENTATION.md) — architecture, binary format, balance model, testing record |

---

## Installation

Copy the files into a folder and run them. Nothing to install.

```bash
python3 setup_check.py        # verifies this machine can run everything
```

`requirements.txt` deliberately lists no packages: every module imports only
from the standard library, so `pip install -r requirements.txt` succeeds and
installs nothing.

The one thing that can be missing is **tkinter**, needed by the two GUI
programs but not by the command-line tools. Some Linux distributions package it
separately:

```bash
sudo apt install python3-tk        # Debian / Ubuntu
sudo dnf install python3-tkinter   # Fedora / RHEL
sudo pacman -S tk                  # Arch
```

macOS and Windows installers from python.org already include it.

`setup_check.py` checks the Python version, the standard library, tkinter, that
all nine files are present and importable, and that the reference data loaded.
It installs nothing and changes nothing. Exit status: `0` ready, `1` command
line only, `2` unusable.

### Files

| File | What it is |
|---|---|
| `h3m_viewer.py` | **read-only** program — run this to inspect |
| `h3m_editor.py` | **editing** program — run this to change a map |
| `h3m.py` | the parser, editor API and command-line tool |
| `h3m_gui.py` | shared window implementation behind both programs |
| `h3m_render.py` | drawing code: palettes, tile index, hover text |
| `h3m_balance.py` | balance model, suggestions, auto-balance |
| `h3m_creatures.py` | reference data: AI values, combat stats, artifact classes |
| `h3m_army.py` | army composition (fill a stack to a total) |
| `h3m_report.py` | HTML analysis report generator |

**All nine must sit in the same folder** and keep their names — `h3m_render.py`
(drawing code) and `h3m_viewer.py` (the read-only program) are different files
despite the similar names. Both entry points check this on launch and name
anything missing.

---

## The two programs

```bash
python3 h3m_viewer.py MyMap.h3m    # look, measure, export — cannot alter a map
python3 h3m_editor.py MyMap.h3m    # everything above, plus editing
```

They share one window implementation, so hovering, layers, highlighting and the
exports behave identically. The viewer has no Edit menu and no edit panel, so a
map you only meant to inspect cannot be changed by accident.

### Viewing

The map is drawn one pixel per tile and scaled up, so a 144×144 map renders
instantly. Terrain gets its own colour, roads lighten a tile, rivers darken it,
and blocked tiles shade down — which makes the walkable network and the shape of
the landmass readable at a glance. Magic terrain zones are blended tints rather
than markers, since they cover areas.

- **Hover** any tile for terrain, road/river, every object covering it, owner,
  creature stacks with counts, and message text
- **Click** to pin the readout and select the object; its full footprint is
  outlined
- **Tab** switches surface / underground
- **Ctrl + mouse wheel** or `+` / `−` zoom from 1× to 16×
- **View menu** toggles a grid, a coordinate ruler and a passability overlay
  (blocked red, interactive yellow)
- **Layers** panel toggles each object category
- **Highlight** box outlines every object whose type or detail matches what you
  type — "dragon", "gold", "Sharpshooter"

Objects are markered on their *entrance* tile where they have one, so a
castle's marker sits on the tile a hero actually walks onto.

### Editing

Click a tile to pin it. Editable fields appear in the **Edit** panel: message
text, monster count and disposition, hero and town names, owner, resource
amount.

**Creature stacks inside an object** — the guards on an artifact, a garrison, a
hero's army, the creatures an event or Pandora's Box hands over — appear as
their own rows with a creature dropdown and an amount box.

**Delete object** removes the whole object. Deleting shifts the index of every
later object, so a saved-and-reloaded map renumbers; positions and contents are
unaffected.

**Edit ▸ Pending changes** lists everything queued, each with its own **undo**,
so you can drop individual changes rather than discarding the lot. Nothing
reaches disk until **Edit ▸ Save map as…**.

Fields shown as words rather than numbers — owner, disposition, never flees,
does not grow — are dropdowns holding exactly the values the format allows.

### Story text

**Edit ▸ Story text editor…** gives a filterable list of every string in the map
on one side and an editable box on the other. Text is stored with an explicit
length, so replacements can be longer or shorter and line breaks are preserved.

For bulk work such as translation there is a file round trip:

```bash
python3 h3m.py MyMap.h3m --export-texts texts.json
# …edit the "text" values, leave "id" alone…
python3 h3m.py MyMap.h3m --import-texts texts.json --save MyMap_edited.h3m
```

### Filling a stack to a total

With a garrison, guard or hero army selected, **Fill to…** sets the counts so
the stack reaches a total number of hit points or of combat power.

Counts are spread in proportion to **weekly growth**, the game's own statement
of how common each creature is meant to be. Ask for 10,000 hit points of
Peasants, Boars and Azure Dragons and you get 220 / 52 / 9 rather than ten
thousand Peasants. The **Mix** slider tilts that towards a horde of low tiers or
a small elite force while still hitting the same total. **Use the map's norm**
fills the target from the balance model.

---

## How writing avoids corrupting the file

Nothing in an `.h3m` refers to a byte position elsewhere. There is no offset
table, no index, no checksum — the format is a single flat stream read front to
back. So a length-prefixed string can be replaced with a longer or shorter one
and everything after it simply shifts.

The writer therefore does not re-serialise the map. The parser records the exact
byte range of every editable field, and saving splices new bytes into those
ranges, back to front. Every byte the parser skipped over is carried through
untouched.

Four guards:

- **Range checks** — a monster count over 65,535 or an unknown player is
  rejected when you queue it, not when you save.
- **Overlap detection** — two edits to the same field are refused.
- **Verify before write** — the edited bytes are re-parsed in memory first. A
  parse failure, trailing bytes, or an unexpected object count aborts the write.
- **Per-change undo** — nothing is committed until you save.

**The gzip container matters too.** Heroes 3 reads the gzip header as a fixed
ten bytes and does not skip the optional filename field, so a file written with
Python's `gzip.GzipFile(path, ...)` — which embeds the output filename — will
not open in the game even though the map inside is valid. The writer builds the
gzip stream by hand to match real `.h3m` files exactly. Re-saving repairs a file
damaged this way:

```bash
python3 h3m.py Broken.h3m --save Fixed.h3m
```

**Verified by round trip.** Loading and saving all 19 test maps with no edits
reproduces the original decompressed bytes *exactly*, with a matching gzip
header. Rewriting every editable string on every map (3,717 strings,
deliberately both longer and shorter) re-parses cleanly each time.

This edits values in place and can remove objects. It cannot add objects, resize
the map or change terrain — for that you still want the official editor.

---

## Balance analysis

Learns how guard stacks are placed across reference maps you supply, then shows
where your own map departs from that.

```bash
python3 h3m_balance.py --reference good1.h3m good2.h3m good3.h3m \
                       --analyze mymap.h3m \
                       --report balance.md --csv balance.csv
```

In the GUI: **Balance ▸ Load reference maps…**, then **Analyse this map**.
Monster markers recolour by verdict and hovering shows the suggestion with its
reasoning.

### Creature strength

Power comes from the game's own **AI Values**, transcribed from *Tribute to
Strategists* (Rainalkar, 2008), combined with combat stats from the Heroes 3
creature power chart.

AI Value alone undervalues mobility: it rates a **Dendroid Soldier** (AI 803,
speed 4) above a **Vampire Lord** (AI 783, speed 9, flying). So:

```
power = AI_value × (speed / 6.5) ^ 0.5 × (ranged ? 1.15) × (flying ? 1.10)
```

which moves the Dendroid Soldier to 630 and the Vampire Lord to 1013. All four
constants sit at the top of `h3m_creatures.py`; set the speed exponent to 0 for
plain AI Values.

Nothing is invented — a creature with no AI Value returns `None` rather than a
guess. As a consistency check the tool correlates effective power against
creature tier and reports the result (r = 0.92 on the test corpus).

### Targets are relative to your own map

Reference maps of the *same size* differ by up to **50×** in how large their
stacks are, so there is no universal correct guard strength to impose. What *is*
consistent between mapmakers is the **ratio**: how much a guard on an artifact
is worth relative to that map's own typical guard.

| Guarding | Typical | Guarding | Typical |
|---|---|---|---|
| seer hut | 0.11× | treasure chest | 0.62× |
| treasure artifact | 0.16× | gold pile | 0.78× |
| creature bank | 0.32× | event | 1.20× |
| mine | 0.38× | Pandora's Box | 1.26× |
| minor artifact | 0.47× | major artifact | 2.83× |
| dwelling | 0.57× | relic | 3.06× |

Rewards are specific: artifacts split by class, resources by type and size,
mines by type. A verdict of "much too strong" means *large compared with the
rest of your map, given what it guards* — never "your map should look like
someone else's".

Each stack gets **one target** with a tolerance around it, plus a **confidence**
label reflecting how much the reference maps agree. Across the test corpus the
median current-to-suggested ratio is 1.02.

### What a guard is really protecting

A single Behemoth on an isthmus can be the only thing between a player and two
mines, a dwelling and several resource piles. Selecting a wandering monster
flood-fills the passability grid with that monster treated as a wall; if it
seals a pocket, the pocket is shaded on the map, its contents circled, and the
hover panel lists them:

```
seals a 10-tile pocket containing 2x treasure chest, 2x resource,
2x artifact, seer hut, dwelling
```

### Auto-balance

**Balance ▸ Auto-balance creature counts…** resizes stacks to sit at the norm
for what they guard.

The key control is the **window**. A stack at 20× the norm is usually a
deliberate set piece — a final boss, a gate meant to hold for hours — so by
default only stacks between **0.5× and 5×** are touched. **Aim for N× the norm**
scales every target, so 1.15 makes the map 15% harder throughout.

Preview lists every proposed change with a checkbox and a **show** button that
jumps the map to that stack. Queued changes appear under **Pending changes**
with per-item undo. A Markdown report records every resize.

```bash
python3 h3m_balance.py --reference good*.h3m --analyze mymap.h3m \
                       --auto-balance mymap_balanced.h3m --window 0.5 5
```

### Quantity: Random

A stack reported as **random quantity** is set to *Quantity: Random* in the
editor, so the game picks its size at load time from map difficulty. That is
about the amount, not the creature type. Those stacks cannot be balanced
deliberately, which is why they are reported separately; auto-balance can give
them fixed amounts if you tick the option.

### Beyond individual stacks

- **Fairness between players** — every object is assigned to the nearest start,
  giving each player a territory, then mines, resources, artifacts, dwellings
  and guard power are compared. A large spread is usually a map's biggest
  balance problem.
- Distance to each player's first guard, ranged and flying guards near starts,
  unguarded artifacts, and the hero level cap.

### Corpus quality

Creature power comes from AI Values, so a thin corpus cannot distort what a
creature is worth. What the reference maps decide is the ratio table. A reward
type is used only when at least 3 maps back it, and the report shows how many.
Because targets are relative, adding reference maps of a different size or style
is safe: they contribute ratios, not scale.

---

## HTML analysis report

```bash
python3 h3m_report.py MyMap.h3m -o report.html
python3 h3m_report.py MyMap.h3m --reference good1.h3m good2.h3m   # adds balance
```

In the GUI: **Export ▸ HTML analysis report…**

One self-contained HTML file — no server, no assets, no internet — covering
overview, an interactive map, terrain breakdown, balance, players, towns,
heroes, monsters, artifacts, spells, mines, dwellings, quests, events, signs and
rumors, keymasters and portals, restrictions, and object counts.

The map is a real image: the tile grid is encoded as a PNG by hand with `zlib`,
so nothing needs an image library. Artifacts are listed with their *parent* —
whether each lies on the map, sits in a named hero's backpack, comes out of an
event, or is a Seer's Hut reward.

---

## Command line

```bash
python3 h3m.py MAP.h3m                       # readable summary
python3 h3m.py MAP.h3m --objects             # every object with x,y,z
python3 h3m.py MAP.h3m --objects --filter mine
python3 h3m.py MAP.h3m --csv objects.csv     # spreadsheet of all objects
python3 h3m.py MAP.h3m --json map.json       # structured dump
python3 h3m.py MAP.h3m --texts story.md      # all human-written text
python3 h3m.py MAP.h3m --armies armies.csv   # every creature stack
python3 h3m.py MAP.h3m --terrain-csv t.csv   # one row per map tile
python3 h3m.py MAP.h3m --export full.json    # full tile-keyed export
```

As a library:

```python
from h3m import parse_file

m = parse_file("MyMap.h3m")
print(m["name"], m["size"], m["difficulty"])

for o in m["objects"]:
    print(o["x"], o["y"], o["z"], o["name"], o.get("owner", ""))
```

### Coordinates

`x` is the column, `y` the row, `z` is `0` for the surface and `1` for the
underground. Origin is top-left. Multi-tile objects are stored at their
**bottom-right** anchor tile, matching the map editor, so a castle listed at
`(77,65)` occupies tiles up and to the left of that point.

### Verifying a parse

The format is a flat byte stream with no internal offsets, so a single wrong
field width silently corrupts everything after it. The parser reports how many
bytes were left unconsumed:

```
[parser consumed everything except 0 trailing bytes; non-zero leftovers: False]
```

`0` means every field width was correct from the first byte to the last. If you
ever get a non-zero number on another map, the parse desynced and the object
list past that point is not trustworthy.

### Full export

`--export` writes one JSON with these top-level nodes:

| Node | Contents |
|---|---|
| `meta` | version, name, size, difficulty, victory/loss conditions, teams |
| `players` | all 8 slots: playability, allowed towns, main town, starting hero |
| `restrictions` | allowed heroes/artifacts/spells/skills, custom hero setups |
| `story` | description, rumors, timed events, signs, seer dialogue, monster messages, Pandora/event text, town events, hero biographies |
| `objects` | every object in full detail, keyed by object index |
| `map` | **tile-keyed**, `"x,y,z"` → terrain + objects + creature stacks |
| `heroes` `towns` `monsters` `mines` `dwellings` `artifacts` `resources` `quests` | themed indexes |
| `statistics` | object counts by type, terrain distribution, per-player totals |

A tile looks like this:

```json
"75,65,0": {
  "terrain": {"terrain": "Swamp", "river": "None", "road": "Dirt"},
  "objects": [
    {"index": 0, "name": "Town", "object_id": 98, "role": "footprint",
     "blocked": true, "visitable": true, "summary": "Castle Longbow",
     "owner": "Red"}
  ],
  "creatures": [
    {"source": "Town garrison", "creature": "Grand Elf", "count": 3,
     "object_index": 0}
  ]
}
```

Multi-tile objects appear on **every tile they cover**, tagged `anchor` or
`footprint`, with `visitable` marking the entrance. `--slim` and `--compact`
roughly halve the file size.

---

## Limitations

- **Horn of the Abyss and WoG maps are not supported.** Both add fields
  throughout the header; they are rejected with a clear error rather than
  mis-parsed.
- No object creation, map resizing or terrain editing.
- Decorative scenery names (object ids ~114–211) are approximate; the `def`
  sprite name in the export is always authoritative. Gameplay object names were
  cross-checked against sprite filenames.
- Guard region analysis assumes 8-directional land movement and ignores boats,
  teleporters and subterranean gates, so a pocket reported as sealed may be
  reachable another way.
- Maps made with modified editors can contain assets the retail game cannot
  load; such a map may parse here yet fail to open in the official editor for
  reasons unrelated to this toolkit.

---

## Credits and licence

Creature AI Values and artifact classes are transcribed from *Tribute to
Strategists* (Rainalkar, 2008). Combat stats come from the Heroes 3 creature
power chart.

Heroes of Might & Magic III is the property of its respective rights holders.
This project is an independent tool that reads and writes map files; it contains
no game assets. Map files are the work of their authors and are not included
here.

Released under the MIT Licence — see [`LICENSE`](LICENSE).
