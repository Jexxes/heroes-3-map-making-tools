# HoMM3 Map Toolkit — Technical Documentation

A read/write toolkit for Heroes of Might & Magic III map files (`.h3m`),
covering parsing, rendering, analysis, balance modelling and editing.

Python 3.8+, standard library only. `tkinter` is required for the two GUI
programs and ships with Python on Windows and macOS; on Linux install
`python3-tk`. Everything else — parser, balance engine, HTML reports, PNG
encoding — has no third-party dependencies at all.

---

## 0. Installation and dependencies

Nothing needs installing. `requirements.txt` lists no packages by design: every
module imports only from the standard library (`argparse`, `base64`,
`binascii`, `collections`, `csv`, `gzip`, `html`, `json`, `math`, `os`,
`statistics`, `struct`, `sys`, `tempfile`, `tkinter`, `traceback`,
`webbrowser`, `zlib`).

`tkinter` is standard library but ships as a separate OS package on several
Linux distributions. Only the two GUI programs need it; the command-line tools
and the library API do not.

`setup_check.py` verifies the environment and installs nothing:

| Check | Failure means |
|---|---|
| Python ≥ 3.8 | nothing will run |
| Standard library complete | cut-down or embedded Python |
| tkinter importable | GUIs blocked, command line fine |
| All nine files present | files not copied together, or renamed |
| Modules import cleanly | a file is truncated or corrupted |
| Reference data loaded | balance results would silently degrade |

Exit status: `0` fully usable, `1` command line only, `2` unusable. `--quiet`
suppresses output for use in scripts.

---

## 1. Architecture

Nine modules, layered so that each one depends only on those below it.

```
  h3m_viewer.py      h3m_editor.py        entry points (read-only / editing)
          \             /
           h3m_gui.py                     shared tkinter window
          /      |       \
 h3m_render  h3m_balance  h3m_report      drawing / analysis / HTML
      |        /     \        |
      |  h3m_army   h3m_creatures         composition / reference data
      \_______|_________|_______/
                 h3m.py                   format: parse, edit, write
```

| Module | Lines | Responsibility |
|---|---|---|
| `h3m.py` | 2145 | Binary format: parsing, field tracking, editing, writing, exports |
| `h3m_gui.py` | 1526 | Shared tkinter window; `READ_ONLY` switches editing off |
| `h3m_balance.py` | 1194 | Guard-stack modelling, suggestions, auto-balance, guard analysis |
| `h3m_report.py` | 643 | Self-contained HTML analysis report |
| `h3m_creatures.py` | 396 | Reference data: AI values, combat stats, artifact classes |
| `h3m_render.py` | 365 | Palettes, tile index, passability, hover text |
| `h3m_army.py` | 173 | Army composition to a target total |
| `h3m_viewer.py` | 51 | Read-only entry point |
| `h3m_editor.py` | 50 | Editing entry point |

There are no cycles. `h3m.py` imports nothing from the toolkit, so the parser
can be used as a library on its own.

Both entry points check on launch that every file is present and name any that
are missing, rather than failing with an import traceback.

---

## 2. The `.h3m` format as this toolkit treats it

A `.h3m` file is a gzip-compressed, flat binary stream. Three properties drive
the whole design:

1. **No offset table.** Nothing in the file refers to a byte position
   elsewhere. There is no index, no directory, no checksum.
2. **Strings are length-prefixed** (`uint32` length, then cp1252 bytes).
3. **Field widths depend on the format version**, which is the first `uint32`:
   `0x0E` Restoration of Erathia, `0x15` Armageddon's Blade, `0x1C` Shadow of
   Death. Horn of the Abyss (`0x20`) and WoG (`0x33`) are rejected with a clear
   error rather than mis-parsed.

Consequence (1) is what makes safe editing possible: a string can be replaced
with a longer or shorter one and everything after it simply shifts.

### Parse order

```
header → players[8] → victory/loss → teams → allowed heroes
→ disposed heroes → allowed artifacts/spells/skills → rumors
→ per-hero settings → terrain grid → object templates → objects
→ timed events → trailing padding
```

The terrain grid is `size × size × levels` tiles of 7 bytes each. Object
templates carry a `.def` sprite name plus 6-byte block and visit masks. Objects
are `x, y, z`, a template index, 5 reserved bytes, then a body whose shape
depends on the template's object class.

### Verification strategy

Because the format is a flat stream, a single wrong field width silently
corrupts everything after it. The parser therefore reports `_bytes_left` after
consuming the file. **Zero trailing bytes means every field width was correct
from the first byte to the last.** All 19 test maps parse to zero.

This check found a real bug during development: a Pandora's Box handler that
skipped 8 padding bytes twice, which desynchronised object 4,603 onward.

### Coordinates

`x` is the column, `y` the row, `z` is 0 for surface and 1 for underground.
Origin is top-left. Multi-tile objects are anchored at their **bottom-right**
tile, matching the map editor. Heroes and boats have their visitable tile one
tile left of their anchor — normal for the format, not a bug.

### Footprints

Each template holds a 6-row × 8-column mask. The bottom-right cell of that grid
is the object's stored position, so offsets run −7..0 in x and −5..0 in y. A
cleared bit in the block mask means the tile is blocked; the visit mask marks
the tile a hero interacts with.

```python
blocked   = not ((block_mask[row] >> col) & 1)
visitable = bool((visit_mask[row] >> col) & 1)
dx, dy    = col - 7, row - 5
```

Overlay objects such as magic terrain carry an **empty** mask; they still
occupy their anchor tile and are registered there explicitly. Missing this made
them invisible to hover and to the JSON export.

---

## 3. Editing and writing

### Field tracking

During parsing, every editable field records its byte range into an `_off` dict
on the object that owns it:

```python
o["_off"]["message"] = ("string", 371503, 371523)   # kind, start, end
```

Objects also record `_span`, the byte range of the whole object record, which
is what deletion removes.

### Applying changes

Edits are queued, never applied immediately:

```python
m = h3m.parse_file("map.h3m")
sign = [o for o in m["objects"] if o["object_id"] == 91][0]
h3m.edit(m, sign, "message", "New text, any length")
h3m.edit(m, town, "owner", "Purple")
h3m.delete_object(m, some_monster)
h3m.save(m, "out.h3m")
```

`save()` splices queued edits into the raw decompressed bytes **back to front**,
so earlier offsets stay valid. Deletions additionally rewrite the object-count
`uint32`. Everything the parser skipped over is carried through untouched.

### Editable fields

| Where | Fields |
|---|---|
| Map | `name`, `description` |
| Monster | `count`, `disposition`, `never_flees`, `does_not_grow`, `message` |
| Hero | `owner`, `hero_id`, `hero_name` |
| Town | `owner`, `town_name` |
| Sign / bottle | `message` |
| Artifact / resource / Pandora / event | `message`, `amount` |
| Mine / garrison / dwelling | `owner` |
| Quest | `first_visit_text`, `next_visit_text`, `completed_text` |
| Rumor, timed event, town event | `name`, `text` / `message` |
| Any creature slot | `creature_id`, `count` |

Fields the parser shows as words (`owner`, `disposition`, `never_flees`,
`does_not_grow`, `creature_id`) accept the label as well as the raw number;
`h3m.field_choices(key)` returns the allowed values.

### Safety

Four independent guards:

- **Range checks** at queue time — a count above 65,535 or an unknown player
  is rejected before it can be written.
- **Overlap detection** — two edits touching the same bytes are refused.
- **Verify before write** — the edited bytes are re-parsed in memory; a parse
  failure, non-zero trailing bytes, or an unexpected object count aborts the
  write.
- **Per-change undo** — `pending_edits()` / `revert_edit()` back the GUI's
  pending-changes list.

### The gzip container

Heroes 3 reads the gzip header as a fixed ten bytes and does **not** skip the
optional filename field. Python's `gzip.GzipFile(path, ...)` writes the output
filename into the header, producing a file whose map data is valid but which
the game reads starting from the filename. `gzip_h3m()` therefore builds the
stream by hand: magic, deflate, no flags, mtime 0, XFL 0, OS 11 — byte-identical
in shape to real `.h3m` files.

This was a real shipped bug. It slipped through because the round-trip test
compared *decompressed* bytes, which were perfect. The regression suite now
checks the container too.

### Round-trip guarantees

- Load and save with no edits reproduces the original decompressed bytes
  **exactly** — 19 of 19 maps byte-identical, with a matching gzip header.
- Rewriting **every** editable string on every map (3,717 strings, deliberately
  both longer and shorter) re-parses cleanly each time, with terrain,
  templates and object count intact.
- Targeted edits change only the intended objects: of 18,880 objects on one
  map, exactly the 2 edited ones differed.

### What editing cannot do

Values are changed in place and objects can be removed, but nothing can be
**added**: no new objects, no map resize, no terrain changes. Deleting shifts
the index of every later object, so a saved-and-reloaded map renumbers
(positions and contents are unaffected).

---

## 4. Reference data

`h3m_creatures.py` holds transcribed data, not guesses.

| Data | Rows | Source |
|---|---|---|
| AI Values | 146 | *Tribute to Strategists* (Rainalkar, 2008), AI Values table |
| Combat stats | 141 | Heroes 3 creature power chart (speed, HP, attack, defence, damage, growth, cost) |
| Artifact classes | 141 | Same manual, Artifact Merchant price tables |
| Dwelling creatures | 73 of 80 subtypes | decoded from dwelling sprite names in `h3m.py` |

**Creature stats are matched by name, not by ID.** The power chart's own `ID`
column does not correspond to h3m creature ids — its Fortress and Conflux
orderings differ and it omits the unused Conflux slots. Joining on ID would
have silently given Gorgon's stats to Serpent Fly.

Ranged and flying flags are curated sets, used for modifiers and reporting.

### Effective power

AI Value is the game's own creature valuation and the right starting point,
but it undervalues mobility: it rates a Dendroid Soldier (AI 803, speed 4)
above a Vampire Lord (AI 783, speed 9, flying). So:

```
power = AI_value × (speed / 6.5) ^ 0.5 × (ranged ? 1.15) × (flying ? 1.10)
```

That moves the Dendroid Soldier to 630 and the Vampire Lord to 1013. All four
constants sit at the top of the module. Setting the speed exponent to 0 gives
plain AI Values back.

A creature with no AI Value returns `None` rather than a fabricated number;
only the unused creature slots fall back to a tier estimate.

**Consistency check:** effective power correlates with creature tier at
**r = 0.92** across the creatures appearing in the test corpus, and median
power rises monotonically through every tier (1.2, 2.3, 4.0, 6.3, 12.4, 19.8,
46.8).

---

## 5. The balance model

### What was measured, and what was discarded

Two hypotheses were tested against a 19-map corpus and **rejected**:

- **Learning creature power from placement counts.** Self-referential, and
  distorted by set-piece stacks — one map's 5,000 Vampire Lords taught the
  model that a tier-4 creature was weaker than a Peasant. Replaced with AI
  values.
- **Guards get tougher further from a start.** Measured per map, the rank
  correlation between distance and guard strength is **r = +0.02**, positive in
  only 6 of 12 maps and strongly negative in several. Distance is still
  recorded and reported as context but sizes nothing. The model prints this
  correlation on every run, so a different corpus can overturn it.

A third finding shaped everything else: reference maps of the **same size**
differ by up to **50×** in how large their stacks are (median guard power
ranged 15,869 to 785,246 across the 144×144 maps). There is no universal
correct guard strength to impose.

### What the model actually is

What *is* consistent between mapmakers is the **ratio**: how much a guard on a
given reward is worth relative to that map's own typical guard. Ratios are
measured inside each map, then combined across maps (median of per-map medians,
so one map is one vote).

| Guarding | Typical | Guarding | Typical |
|---|---|---|---|
| seer hut | 0.11× | treasure chest | 0.62× |
| treasure artifact | 0.16× | gold pile | 0.78× |
| creature bank | 0.32× | event | 1.20× |
| mine | 0.38× | Pandora's Box | 1.26× |
| minor artifact | 0.47× | major artifact | 2.83× |
| dwelling | 0.57× | relic | 3.06× |
| | | combination artifact | 6.93× |

Reward types are specific: artifacts split by class, resources by type and
size, mines by type. Lumping a Centaur Axe in with the Sandals of the Saint
was a major source of noise.

### Applying it

The target map's own **anchor** — its typical guard — is inferred from all its
stacks after dividing out what each one guards. Each target is then
`anchor × ratio × user_scale`.

```
suggested_count = anchor × ratio × scale / creature_power
```

A verdict of "much too strong" therefore means *large compared with the rest of
your map, given what it guards*, never "your map should look like someone
else's".

**Calibration:** across all 19 maps the median current-to-suggested ratio is
**1.02**, and about two thirds of stacks land inside their own band.

### Suggestions are one number plus confidence

An earlier version quoted the corpus spread as the suggestion, producing
"suggested 14–755". The spread was real — within a reward type the reference
maps genuinely vary by an order of magnitude — but reporting it as a range was
the wrong response.

Each stack now gets one target with a design tolerance of 0.6×–1.6×, and the
corpus spread is reported separately as a **confidence** label derived from a
robust log-space sigma (MAD-based, so outliers cannot inflate it). Median band
width went from ~54× to **2.7×**.

### Guard region analysis

Classifying a guard by "nearest valuable within 3 tiles" is too crude. A single
monster on an isthmus can be the only thing between a player and several mines,
a dwelling and a pile of resources.

`guarded_region()` builds a passability grid, treats the guard as a wall, and
floods outward from each free neighbour. If the regions do not join, the
smaller one is the sealed pocket; everything valuable inside it is what the
guard actually protects. Roughly 40% of wandering monsters in the corpus seal a
pocket this way. Cost is 2–5 seconds for a whole map, so it runs on selection
rather than during model building.

### Beyond individual stacks

- **Player fairness** — every object is assigned to its nearest start, forming
  territories, then mines, resources, artifacts, dwellings and guard power are
  compared. A large spread is usually a map's biggest balance problem.
- **Opening difficulty** per player, ranged/flying guards near starts,
  unguarded artifacts, hero level cap, random-quantity stacks.

**Start positions** are one per player: the declared main town, falling back to
a single owned town. Counting every owned town as a start (an early bug) gave
"32 starts" on an 8-player map and collapsed every distance measurement.

### Quantity: Random

A stack with `count == 0` is set to *Quantity: Random* in the editor — the game
picks its size at load time from map difficulty. This is about the amount, not
the creature type. Such stacks are reported separately rather than counted as
mistakes, and auto-balance can give them fixed amounts on request.

---

## 6. Army composition

`h3m_army.compose()` sets counts so a stack reaches a target total of hit
points or of combat power.

Counts are spread in proportion to **weekly growth**, the game's own statement
of how common each creature is meant to be. Without that, "10,000 HP of
Peasants, Boars and Azure Dragons" yields ten thousand Peasants; with it, 220 /
52 / 9.

A `tier_tilt` parameter (−1.5 to +1.5) shifts the mix towards low or high tiers
while still hitting the same total:

```
weight = growth × 2 ^ (tier_tilt × (tier − 4) / 2)
```

After proportional allocation the result is refined greedily, nudging whichever
slot best closes the remaining gap. Targets are typically hit exactly (±0.00%).

Composition is **positional**, not keyed by creature id, because a garrison may
legitimately hold the same creature in two slots — keying by id double-counted
them.

`norm_target()` derives a target from the balance model so a filled garrison
sits where a guard of that kind belongs on that map.

---

## 7. Rendering

`h3m_render.py` is GUI-toolkit-free so it can be tested headlessly and reused
by the HTML report.

- `build_tile_index(m)` → `(x, y, z)` → list of `{index, role, blocked, visitable}`
- `build_terrain_index(m)` → `(x, y, z)` → `(terrain, river, road)`
- `base_rows(m, z, ...)` → rows of `#rrggbb`, one per tile
- `markers(m, z)` → non-scenery objects with colour, shape and category
- `tile_info(...)` → the hover readout
- `passability_grid(m, z)` → `PASS_FREE` / `PASS_BLOCKED` / `PASS_VISITABLE`
- `flood(...)` → 8-directional fill used by guard analysis

Terrain gets its own colour; roads lighten a tile, rivers darken it, blocked
tiles shade down. Magic terrain zones are blended tints rather than markers,
since they cover areas — this alone cut marker clutter from 2,038 to 1,429 on a
144×144 map.

The passability overlay is baked into the tile colours rather than drawn as
canvas items, so it stays fast at any zoom.

In the GUI the map is a `tkinter.PhotoImage` at one pixel per tile, scaled with
integer `zoom()`. A 144×144 map builds in about 0.5 s end to end. In the HTML
report the same rows are encoded as a PNG by hand with `zlib` — a ~20-line
encoder — so no image library is needed.

---

## 8. Exports

| Export | Contents |
|---|---|
| Summary (text) | Header, players, object counts, towns, heroes |
| Objects (CSV) | One row per object: `x, y, z, object_id, subid, type, def, owner, detail` |
| Creature stacks (CSV) | Every stack from any source, with counts and notes |
| Story text (Markdown) | All authored text grouped by kind |
| Story text (JSON) | Same, round-trippable for bulk editing |
| Terrain (CSV) | One row per tile |
| Full export (JSON) | Tile-keyed map plus themed indexes |
| HTML report | 18-section self-contained analysis page |
| PDF report | the same page printed by a browser |
| Balance report / CSV | Model tables, warnings, per-stack verdicts |
| Auto-balance report | Every resize with coordinates and prior ratio |

### PDF

The report is printed by a browser rather than redrawn with a PDF library:
same HTML, same SVG charts, no extra dependency. A `@media print` block flips
the palette to a light one — because every colour is a custom property,
redefining the properties recolours the charts too — removes the fixed table
heights so tables print in full, repeats table headers on each page with
`display:table-header-group`, and keeps rows and charts from breaking across
pages.

`write_pdf()` locates a Chromium-based browser (PATH first, then the usual
Windows and macOS install paths) and runs it headless with `--print-to-pdf`.
If none is found it raises `PdfUnavailable` with instructions for the manual
route, which produces the same document. Nothing about the toolkit's
zero-dependency position changes: without a browser you lose the automated
PDF, not the report.

`SECTION_IDS` lists the sections; `sections=` and `exclude=` scope the output,
which matters mainly for PDFs, where a full report on a 144x144 map runs to
about 99 pages versus 26 for a scoped one.

### Full JSON export

Top-level nodes: `meta`, `players`, `restrictions`, `story`, `objects`, `map`,
`heroes`, `towns`, `monsters`, `mines`, `dwellings`, `artifacts`, `resources`,
`quests`, `statistics`.

`map` is keyed `"x,y,z"`:

```json
"75,65,0": {
  "terrain": {"terrain": "Swamp", "river": "None", "road": "Dirt"},
  "objects": [{"index": 0, "name": "Town", "role": "footprint",
               "blocked": true, "visitable": true}],
  "creatures": [{"source": "Town garrison", "creature": "Grand Elf",
                 "count": 3, "object_index": 0}]
}
```

Multi-tile objects appear on every tile they cover, tagged `anchor` or
`footprint`, with `index` cross-referencing the `objects` node. `--slim` and
`--compact` cut size by roughly half; a 144×144 map with 18,880 objects is
about 16 MB slim.

---

## 9. Command line

```bash
# reading
python3 h3m.py MAP.h3m                       # summary
python3 h3m.py MAP.h3m --objects --filter mine
python3 h3m.py MAP.h3m --csv o.csv --json m.json --armies a.csv
python3 h3m.py MAP.h3m --texts story.md --terrain-csv t.csv
python3 h3m.py MAP.h3m --export full.json --slim --compact

# text round trip
python3 h3m.py MAP.h3m --export-texts texts.json
python3 h3m.py MAP.h3m --import-texts texts.json --save MAP_edited.h3m

# HTML report
python3 h3m_report.py MAP.h3m --reference good1.h3m good2.h3m -o report.html

# balance
python3 h3m_balance.py --reference good*.h3m --analyze MAP.h3m \
                       --report balance.md --csv balance.csv
python3 h3m_balance.py --reference good*.h3m --analyze MAP.h3m \
                       --auto-balance out.h3m --window 0.5 5

# GUIs
python3 h3m_viewer.py MAP.h3m
python3 h3m_editor.py MAP.h3m
```

Re-saving with no edits also repairs a file written by a tool that produced a
non-standard gzip header.

---

## 10. Testing

There is no test framework; verification is done by running the tools over a
corpus of 19 real maps ranging from 36×36 to 144×144, RoE through SoD, 1,075 to
18,880 objects.

| Check | Result |
|---|---|
| Parse to zero trailing bytes | 19/19 |
| Save with no edits → identical decompressed bytes | 19/19 |
| Save with no edits → correct bare gzip header | 19/19 |
| Rewrite every string, re-parse cleanly | 19/19, 3,717 strings |
| Targeted edit changes only intended objects | verified (2 of 18,880) |
| Auto-balance, every change verified on disk | 19/19, 1,649 resizes |
| Auto-balance including random-quantity | 19/19, 292 changes verified |
| Creature power vs tier correlation | r = 0.92 |
| Suggestion calibration (median ratio) | 1.02 |
| GUI interaction checks under Xvfb | 17/17 |
| HTML report rendered in headless Chromium | no JS errors; filters, sorting and charts verified |
| Creature dwellings resolved to a creature | 1,312 of 1,387 (94.6%) |

The GUIs are exercised under a virtual display (`Xvfb`) with a real `tkinter`,
covering hover, click-to-pin, the selection outline, the edit panel, the grid,
the ruler gutters (shown, drawn, scroll-synced, non-colliding, hidden again),
the passability overlay, zoom, balance analysis, guard region highlighting and
the story text editor — 17 checks, all passing.

The HTML report is loaded in headless Chromium and asserted to raise no
JavaScript errors, render its charts, and filter correctly: narrowing the
ratio window to 1.0x–2.0x cuts 482 stacks to 113, the verdict dropdown to 48,
and a text search for "dragon" to 14. Menu structure
is asserted separately: the editor exposes File, Export, View, Edit, Balance,
Help; the viewer the same without Edit.

Two layout properties are asserted numerically rather than by eye, because
both were real bugs:

- the map canvas expands to the full available width, and its width does not
  change when a long path is written to the status bar;
- the scroll region is padded symmetrically when the map is smaller than the
  canvas, so the map sits centred.

Visual appearance beyond these assertions is still a matter of judgement and
benefits from a human look.

Design decisions were checked against data rather than asserted: the distance
hypothesis was tested and dropped, learned creature power was tested and
dropped, and the artifact-class refinement was kept because it produced a clean
monotonic ordering.

---

## 11. Known limitations

- **Horn of the Abyss and WoG maps are not supported.** Both add fields
  throughout the header and extra object bodies. They are rejected with a clear
  message rather than mis-parsed. Extending would require sample files to
  verify against.
- **No object creation, resizing or terrain editing.**
- Town building bitmasks decode to names only in the JSON export; hero
  artifacts are reported by slot number.
- Decorative scenery names (object ids roughly 114–211) are approximate; the
  `def` sprite name is always authoritative. Gameplay object names were
  cross-checked against sprite filenames.
- The balance corpus needs several maps to be meaningful. A reward type is used
  only when at least 3 reference maps back it, and the report shows how many.
- Guard region analysis assumes 8-directional land movement and ignores boats,
  teleporters, subterranean gates and one-way monoliths, so a pocket it reports
  as sealed may be reachable another way.
- Maps made with modified editors can contain assets the retail game cannot
  load; such a map may parse here yet fail to open in the editor for reasons
  unrelated to this toolkit.
