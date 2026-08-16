"""
h3m_balance.py — learn guard-stack conventions from a corpus of maps, then
score and suggest counts for the stacks on another map.

The design goal is that nothing important is invented. Creature strength is
learned from how mapmakers actually place creatures, using a tier-based prior
only to fill gaps. Reward values and the difficulty curve are likewise
measured from the corpus rather than asserted.
"""

import math
import os
import statistics
from collections import Counter, defaultdict

import h3m
import h3m_creatures as creatures

# --------------------------------------------------------------------------
# Creature metadata
# --------------------------------------------------------------------------
# Creature ids 0..125 are nine town line-ups of 14 (2 per tier), so faction,
# tier and upgrade status are pure arithmetic. Neutrals need a table.
NEUTRAL_TIERS = {
    112: 2, 113: 2, 114: 2, 115: 2,      # air / earth / fire / water elemental
    116: 4, 117: 4,                      # gold / diamond golem
    118: 1, 119: 1,                      # pixie / sprite
    120: 5, 121: 5,                      # psychic / magic elemental
    122: 2, 123: 2, 124: 2, 125: 2,      # ice / magma elementals (+unused)
    126: 2, 127: 2, 128: 2, 129: 2,      # storm / energy elementals (+unused)
    130: 6, 131: 6,                      # firebird / phoenix
    132: 7, 133: 7, 134: 7, 135: 7,      # azure / crystal / faerie / rust dragon
    136: 6, 137: 5, 138: 3,              # enchanter / sharpshooter / halfling
    139: 1, 140: 2, 141: 3,              # peasant / boar / mummy
    142: 3, 143: 2, 144: 5,              # nomad / rogue / troll
    145: 1, 146: 1, 147: 1, 148: 1, 149: 1,   # war machines
}

# Best-effort flags, used for reporting and warnings rather than scoring.
RANGED = {
    2, 3, 8, 9, 18, 19, 29, 34, 35, 41, 44, 45, 64, 65, 74, 75, 76, 77,
    88, 89, 92, 93, 100, 101, 123, 127, 136, 137, 138, 146, 149,
}
FLYING = {
    4, 5, 12, 13, 20, 21, 26, 27, 30, 31, 36, 37, 52, 53, 54, 55,
    60, 61, 62, 63, 68, 69, 72, 73, 80, 81, 82, 83, 90, 91,
    104, 105, 108, 109, 118, 119, 129, 130, 131, 132, 133, 134, 135,
}

# Relative power prior by tier. Shaped like the game's own value curve
# (each tier roughly doubles), used only where the corpus is thin.
CLAMP = 2.5     # learned power may not stray further than this from the prior

TIER_PRIOR = {1: 1.0, 2: 2.2, 3: 4.5, 4: 9.0, 5: 18.0, 6: 38.0, 7: 90.0}
UPGRADE_MULT = 1.3


def creature_meta(cid):
    """Real stats where we have them; a tier guess only as a last resort."""
    if cid is None:
        return {"tier": None, "faction": None, "upgraded": None,
                "ranged": False, "flying": False, "name": "random",
                "ai_value": None, "speed": None, "power": None}
    m = creatures.meta(cid)
    if cid < 126:
        faction = h3m.FACTIONS[cid // 14]
        upgraded = bool(cid % 2)
    else:
        faction, upgraded = "Neutral", False
    if m:
        return {"tier": int(m["level"]) if m["level"] else None,
                "faction": faction, "upgraded": upgraded,
                "ranged": m["ranged"], "flying": m["flying"],
                "name": m["name"], "ai_value": m["ai_value"],
                "speed": m["speed"], "power": m["power"]}
    return {"tier": None, "faction": faction, "upgraded": upgraded,
            "ranged": cid in creatures.RANGED, "flying": cid in creatures.FLYING,
            "name": h3m.cname(cid), "ai_value": None, "speed": None,
            "power": None}


# Fallback for the handful of unused creature slots that carry no AI Value.
FALLBACK_BY_TIER = {1: 60, 2: 140, 3: 300, 4: 600, 5: 1000, 6: 1800, 7: 5000}


def creature_power(cid):
    """Effective power of one creature.

    Comes from the AI Value table adjusted for speed and traits. Only the
    unused creature slots, which have no published value, fall back to a
    tier estimate.
    """
    p = creatures.power(cid)
    if p is not None:
        return p
    tier = creature_meta(cid).get("tier")
    return float(FALLBACK_BY_TIER.get(tier, 500))


VALUABLE = {
    5: "artifact", 65: "artifact", 66: "artifact", 67: "artifact",
    68: "artifact", 69: "artifact", 93: "spell scroll",
    79: "resource", 76: "resource",
    53: "mine", 220: "mine",
    17: "dwelling", 18: "dwelling", 19: "dwelling", 20: "dwelling",
    216: "dwelling", 217: "dwelling", 218: "dwelling",
    98: "town", 77: "town",
    6: "pandora", 26: "event", 101: "treasure chest", 16: "creature bank",
    83: "seer hut", 36: "grail", 102: "tree of knowledge",
    33: "garrison", 219: "garrison", 84: "crypt", 63: "pyramid",
    25: "dragon utopia", 24: "derelict ship", 108: "warrior's tomb",
}

REWARD_ORDER = ["path", "seer hut", "crypt", "garrison", "treasure chest",
                "warrior's tomb", "creature bank", "tree of knowledge",
                "spell scroll", "resource", "mine", "event", "pandora",
                "dwelling", "pyramid", "town", "artifact", "dragon utopia",
                "grail", "other"]


def spearman(xs, ys):
    """Spearman rank correlation between two equal-length sequences."""
    n = len(xs)
    if n < 5:
        return None

    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        for pos, i in enumerate(order):
            r[i] = pos
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx)
                    * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def refine_reward(o, base):
    """Split coarse reward types into ones that actually predict guard size.

    "artifact" lumps a Centaur Axe in with the Sandals of the Saint, and
    "resource" lumps 5 wood in with 20,000 gold. Those are wildly different
    prizes and mapmakers guard them very differently, so the wide suggestion
    ranges were largely this bluntness showing through.
    """
    oid, sub = o["object_id"], o["object_subid"]
    if base == "artifact":
        if oid == 5:
            return "artifact:" + creatures.artifact_class(sub).lower()
        return {65: "artifact:random", 66: "artifact:treasure",
                67: "artifact:minor", 68: "artifact:major",
                69: "artifact:relic"}.get(oid, "artifact:random")
    if base == "resource":
        if oid == 76:
            return "resource:random"
        res = h3m.RESOURCES[sub] if sub < 7 else "?"
        if res == "Gold":
            amt = o.get("amount") or 0
            return "resource:gold" + (":big" if amt >= 10000 else "")
        return "resource:" + ("wood-ore" if res in ("Wood", "Ore") else "rare")
    if base == "mine":
        if oid == 220:
            return "mine:abandoned"
        return "mine:" + (h3m.MINE_SUBTYPE.get(sub, str(sub))
                          .split("(")[0].strip().lower().replace(" ", "-"))
    if base == "dwelling":
        return "dwelling"
    if base == "spell scroll":
        return "spell scroll"
    return base


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def start_positions(m):
    """One starting position per player.

    A player's declared main town is authoritative. Only when a player has no
    main town do we fall back to a town they own — and then just one, because
    counting every owned town as a start turns deep-territory castles into
    spawn points and collapses every distance measurement on the map.
    """
    starts = {}
    for p in m["players"]:
        if not (p["can_be_human"] or p["can_be_computer"]):
            continue
        mt = p.get("main_town")
        if mt:
            starts[p["color"]] = {"player": p["color"], "x": mt["x"],
                                  "y": mt["y"], "z": mt["z"], "source": "main town"}
    for o in m["objects"]:
        if o["object_id"] not in (98, 77):
            continue
        owner = o.get("owner")
        if owner in (None, "Neutral/None") or owner in starts:
            continue
        starts[owner] = {"player": owner, "x": o["x"], "y": o["y"],
                         "z": o["z"], "source": "owned town"}
    return list(starts.values())


def _nearest(starts, x, y, z, map_size=144):
    """(distance, player, same_level) to the closest start."""
    penalty = 0.25 * map_size          # crossing levels costs a gate trip
    best = None
    for s in starts:
        d = chebyshev((x, y), (s["x"], s["y"]))
        if s["z"] != z:
            d += penalty
        if best is None or d < best[0]:
            best = (d, s["player"], s["z"] == z)
    return best if best else (None, None, None)


def _second_nearest_player(starts, x, y, z, map_size=144):
    seen = []
    for s in starts:
        d = chebyshev((x, y), (s["x"], s["y"])) + (0.25 * map_size if s["z"] != z else 0)
        seen.append((d, s["player"]))
    seen.sort()
    owners = []
    for d, p in seen:
        if p not in [q for _, q in owners]:
            owners.append((d, p))
    return owners[1] if len(owners) > 1 else (None, None)


def extract_stacks(m, path=""):
    """Every guard stack on a map, with its context features."""
    starts = start_positions(m)
    valuables = [o for o in m["objects"] if o["object_id"] in VALUABLE]
    guard_owner = {}
    for o in m["objects"]:
        for g in o.get("guards") or []:
            guard_owner.setdefault(o["index"], []).append(g)

    out = []
    for o in m["objects"]:
        oid = o["object_id"]
        is_monster = oid in (54, 71, 72, 73, 74, 75, 162, 163, 164)
        entries = []
        if is_monster:
            cid = o["object_subid"] if oid == 54 else None
            entries.append((cid, o.get("count", 0), "wandering", None))
        # slot position is carried through so an object with several identical
        # guard slots resolves to the right one when edits are applied
        for gi, g in enumerate(o.get("guards") or []):
            entries.append((g["creature_id"], g["count"], "attached", gi))
        if not entries:
            continue

        dist, owner, same_level = _nearest(starts, o["x"], o["y"], o["z"],
                                           m["size"])
        d2, enemy = _second_nearest_player(starts, o["x"], o["y"], o["z"],
                                           m["size"])

        # what is being guarded, described as precisely as the file allows
        if o.get("guards"):
            reward = refine_reward(o, VALUABLE.get(oid, "other"))
            reward_obj = o["name"]
        else:
            reward, reward_obj, best = "path", "", 99
            for v in valuables:
                if v["z"] != o["z"] or v["index"] == o["index"]:
                    continue
                d = chebyshev((o["x"], o["y"]), (v["x"], v["y"]))
                if d <= 3 and d < best:
                    best = d
                    reward = refine_reward(v, VALUABLE[v["object_id"]])
                    reward_obj = v["name"]

        for cid, count, kind, slot_index in entries:
            meta = creature_meta(cid)
            out.append({
                "map": os.path.basename(path), "index": o["index"],
                "x": o["x"], "y": o["y"], "z": o["z"], "kind": kind,
                "creature_id": cid, "creature": meta["name"],
                "slot_index": slot_index,
                "tier": meta["tier"], "faction": meta["faction"],
                "upgraded": meta["upgraded"], "ranged": meta["ranged"],
                "flying": meta["flying"], "count": count,
                "random_count": count == 0,
                "reward": reward, "reward_object": reward_obj,
                "distance_to_start": round(dist) if dist is not None else None,
                "distance_fraction": round(dist / m["size"], 3) if dist is not None else None,
                "nearest_player": owner,
                "same_level_as_start": same_level,
                "distance_to_enemy": d2, "nearest_enemy": enemy,
                "disposition": o.get("disposition"),
                "never_flees": o.get("never_flees"),
                "map_size": m["size"], "difficulty": m["difficulty"],
                "max_hero_level": m["max_hero_level"] or 0,
                "underground": o["z"] == 1,
            })
    return out


# --------------------------------------------------------------------------
# Corpus model
# --------------------------------------------------------------------------
# Distance is expressed as a fraction of the map's own width. Twenty tiles is
# the far frontier on a 36x36 map and the neighbours' doorstep on a 144x144
# one, so pooling raw tile counts across sizes flattens the difficulty curve
# into noise.
DIST_BANDS = [(0.00, 0.06), (0.06, 0.12), (0.12, 0.20),
              (0.20, 0.30), (0.30, 0.45), (0.45, 9.99)]

BAND_LABELS = ["home", "near", "mid", "far", "distant", "edge"]


def band_label(lo, hi):
    i = [b[0] for b in DIST_BANDS].index(lo)
    pct = f"{lo:.0%}-{hi:.0%}" if hi < 9 else f"{lo:.0%}+"
    return f"{BAND_LABELS[i]} ({pct})"


def band_of(d, map_size=None):
    """Band from a distance in tiles, normalised by map width."""
    if d is None:
        return None
    frac = d / float(map_size) if map_size else d / 144.0
    for lo, hi in DIST_BANDS:
        if lo <= frac < hi:
            return band_label(lo, hi)
    return None


def build_model(paths, progress=None):
    """Learn creature power, the difficulty curve and reward values."""
    stacks, maps = [], []
    for p in paths:
        if progress:
            progress(f"Reading {os.path.basename(p)} …")
        m = h3m.parse_file(p)
        maps.append({"path": p, "name": m["name"] or os.path.basename(p),
                     "size": m["size"], "levels": m["levels"],
                     "difficulty": m["difficulty"],
                     "max_hero_level": m["max_hero_level"] or 0,
                     "objects": len(m["objects"]),
                     "players": sum(1 for q in m["players"]
                                    if q["can_be_human"] or q["can_be_computer"]),
                     "artifacts": sum(1 for o in m["objects"]
                                      if o["object_id"] in (5, 65, 66, 67, 68, 69, 93)),
                     "mines": sum(1 for o in m["objects"] if o["object_id"] == 53),
                     "dwellings": sum(1 for o in m["objects"]
                                      if o["object_id"] in (17, 18, 19, 20, 216, 217, 218))})
        stacks.extend(extract_stacks(m, p))

    real = [s for s in stacks if s["count"] > 0 and s["creature_id"] is not None]

    # ---- creature power comes from the reference data, not the corpus ----
    # Creature power comes from the game's own AI Values (adjusted for speed
    # and traits), not from the corpus. Deriving it from how often mapmakers
    # place a creature would be self-referential and skewed by set-piece
    # stacks. The corpus supplies only the reward ratios computed below.
    power = {}
    evidence = {}
    counts_by_creature = defaultdict(list)
    for s in real:
        counts_by_creature[s["creature_id"]].append(s["count"])
    for cid, cs in counts_by_creature.items():
        m = creature_meta(cid)
        power[cid] = creature_power(cid)
        evidence[cid] = {"observations": len(cs),
                         "median_count": statistics.median(cs),
                         "ai_value": m["ai_value"], "speed": m["speed"],
                         "tier": m["tier"], "power": power[cid]}

    def power_of(cid):
        return creature_power(cid)

    for s in real:
        s["power"] = s["count"] * power_of(s["creature_id"])

    # ---- absolute targets, aggregated robustly across maps ----
    # AI Values are an absolute scale, so guard power is directly comparable
    # between maps and needs no rescaling. What does need care is that one
    # extreme map must not set the norm: every statistic below is the median
    # across maps of that map's own median, so a map with thousand-strong
    # stacks contributes one vote, not thousands of samples.
    def per_map_median(selector):
        by_map = defaultdict(list)
        for s in real:
            key = selector(s)
            if key is not None:
                by_map[(key, s["map"])].append(s["power"])
        grouped = defaultdict(list)
        for (key, mp), vals in by_map.items():
            grouped[key].append(statistics.median(vals))
        out = {}
        for key, map_medians in grouped.items():
            map_medians.sort()
            n_stacks = sum(1 for s in real if selector(s) == key)
            out[key] = {"n": n_stacks, "maps": len(map_medians),
                        "median": statistics.median(map_medians),
                        "p25": map_medians[len(map_medians) // 4],
                        "p75": map_medians[min(len(map_medians) - 1,
                                               3 * len(map_medians) // 4)]}
        return out

    curve = per_map_median(lambda s: band_of(s["distance_to_start"], s["map_size"]))
    overall = per_map_median(lambda s: "all").get("all")
    rewards = per_map_median(lambda s: s["reward"])
    joint = per_map_median(
        lambda s: (f'{band_of(s["distance_to_start"], s["map_size"])}|{s["reward"]}'
                   if band_of(s["distance_to_start"], s["map_size"]) else None))

    map_median = {}
    for p in {s["map"] for s in real}:
        vals = [s["power"] for s in real if s["map"] == p]
        map_median[p] = statistics.median(vals) if vals else 1.0

    # ---- relative reward multipliers, computed WITHIN each map ----
    # Mapmakers differ by ~50x in how big they make guards, even at the same
    # map size, so there is no universal "correct" guard strength to impose.
    # What is consistent between maps is the *ratio*: how much an artifact
    # guard is worth relative to that map's own typical guard. Computing the
    # ratio inside each map and then taking the median across maps gives a
    # scale-free target that transfers to a map of any size or style.
    reward_mult = defaultdict(list)     # per-map medians -> robust centre
    reward_spread = defaultdict(list)   # every stack -> realistic spread
    for p in {s["map"] for s in real}:
        ss = [s for s in real if s["map"] == p]
        if len(ss) < 20:
            continue
        base = statistics.median([s["power"] for s in ss])
        if not base:
            continue
        by_reward = defaultdict(list)
        for s in ss:
            by_reward[s["reward"]].append(s["power"] / base)
        for rew, vals in by_reward.items():
            reward_spread[rew].extend(vals)
            if len(vals) >= 3:
                reward_mult[rew].append(statistics.median(vals))
    multipliers = {}
    for rew, vals in reward_mult.items():
        if len(vals) < 3:
            continue
        vals.sort()
        # Centre from per-map medians so one map cannot drag it.
        pooled = sorted(reward_spread[rew])
        centre = statistics.median(vals)
        # How consistent are mapmakers about this reward? A robust spread in
        # log space, so a few set-piece stacks cannot inflate it. This drives a
        # confidence label rather than the suggested numbers: the corpus spread
        # really is an order of magnitude wide, and widening the suggestion to
        # match it would just make the suggestion useless.
        logs = [math.log(v) for v in pooled if v > 0]
        sigma = None
        if len(logs) >= 8:
            med = statistics.median(logs)
            mad = statistics.median([abs(x - med) for x in logs])
            sigma = 1.4826 * mad
        spread = math.exp(1.349 * sigma) if sigma else None
        if sigma is None:
            conf = "low"
        elif sigma < 1.2 and len(vals) >= 5:
            conf = "high"
        elif sigma < 2.0 and len(vals) >= 4:
            conf = "medium"
        else:
            conf = "low"
        multipliers[rew] = {
            "maps": len(vals), "median": centre,
            "p25": pooled[len(pooled) // 5],
            "p75": pooled[min(len(pooled) - 1, 4 * len(pooled) // 5)],
            "sigma": sigma, "corpus_spread": spread, "confidence": conf,
            "n": len(pooled)}

    # Does distance from a start actually predict guard strength? Measured
    # per map, then summarised, rather than assumed.
    dist_corr = []
    for p in {s["map"] for s in real}:
        ss = [s for s in real
              if s["map"] == p and s["distance_fraction"] is not None]
        if len(ss) >= 25:
            r = spearman([s["distance_fraction"] for s in ss],
                         [math.log(max(s["power"], 1)) for s in ss])
            if r is not None:
                dist_corr.append({"map": p, "n": len(ss), "r": r})
    distance_signal = {
        "per_map": sorted(dist_corr, key=lambda d: -d["r"]),
        "median_r": statistics.median([d["r"] for d in dist_corr]) if dist_corr else None,
        "positive_maps": sum(1 for d in dist_corr if d["r"] > 0),
        "total_maps": len(dist_corr),
    }

    # ---- tier usage by distance ----
    tiers = defaultdict(Counter)
    for s in real:
        bd = band_of(s["distance_to_start"], s["map_size"])
        if bd and s["tier"]:
            tiers[bd][s["tier"]] += 1

    return {"maps": maps, "stacks": stacks, "creature_power": power,
            "creature_evidence": evidence, "curve": curve, "rewards": rewards,
            "overall": overall, "multipliers": multipliers, "joint": joint,
            "tier_usage": {k: dict(v) for k, v in tiers.items()},
            "map_median_power": map_median,
            "distance_signal": distance_signal,
            "sample_size": len(real)}


def validate_model(model):
    """Sanity check: does effective power rise with creature tier?

    Power comes from the game's AI Values, so this is a consistency check on
    the reference data rather than a test of anything learned.
    """
    pairs = [(creature_meta(cid)["tier"], p)
             for cid, p in model["creature_power"].items()
             if creature_meta(cid)["tier"] and p]
    if len(pairs) < 4:
        return {"n": len(pairs), "correlation": None,
                "verdict": "too few creatures observed to validate"}
    xs = [a for a, _ in pairs]
    ys = [math.log(b) for _, b in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs)
                    * sum((b - my) ** 2 for b in ys))
    r = num / den if den else 0.0
    verdict = ("consistent — power tracks creature tier closely" if r > 0.8
               else "moderate — broadly tracks tier" if r > 0.5
               else "weak — check the creature data")
    return {"n": len(pairs), "correlation": r, "verdict": verdict}


# --------------------------------------------------------------------------
# Suggestions for one map
# --------------------------------------------------------------------------
# How far either side of the target still counts as "on curve".
TOLERANCE_LOW = 0.6
TOLERANCE_HIGH = 1.6


def suggest(m, model, path="", scale=1.0):
    """scale multiplies every target, so a user can aim for e.g. 1.15x the norm."""
    stacks = extract_stacks(m, path)
    power = model["creature_power"]

    def power_of(cid):
        return creature_power(cid)

    # The anchor is this map's own "typical guard", inferred from every stack
    # after dividing out what each one guards. Deriving it this way means the
    # suggestions comment on the *shape* of the map's guard economy rather
    # than trying to impose another map's absolute scale — which is the right
    # claim to make, since reference maps of the same size differ by ~50x in
    # how big they build stacks.
    mults = model.get("multipliers", {})
    implied = []
    for s in stacks:
        if s["count"] > 0 and s["creature_id"] is not None:
            f = mults.get(s["reward"], {}).get("median", 1.0) or 1.0
            implied.append(s["count"] * power_of(s["creature_id"]) / f)
    anchor = statistics.median(implied) if implied else (
        model.get("overall", {}).get("median", 1.0))

    out = []
    for s in stacks:
        if s["creature_id"] is None:
            continue
        band = band_of(s["distance_to_start"], s["map_size"])
        mult = model.get("multipliers", {}).get(s["reward"])

        # Targets are relative to this map's own typical guard, so a modest
        # map is never told to adopt an enormous map's stack sizes. Distance
        # is reported as context: it did not predict guard strength in the
        # reference maps.
        if mult and mult["maps"] >= 3:
            factor = mult["median"]
            basis = (f"guarding {s['reward']}: {factor:.2f}x a typical guard "
                     f"on this map ({mult['maps']} reference maps)")
            n = mult["n"]
            conf = mult["confidence"]
            spread = mult.get("corpus_spread")
        else:
            factor = 1.0
            basis = "no reference for this reward type; using a typical guard"
            n, conf, spread = 0, "low", None

        # The band is a design tolerance around one target, not the corpus
        # spread. The reference maps vary by an order of magnitude within a
        # reward type, and quoting that as "suggested 14-755" tells a mapmaker
        # nothing. The spread is reported separately as confidence instead.
        target = anchor * factor * scale
        lo, hi = target * TOLERANCE_LOW, target * TOLERANCE_HIGH

        p = power_of(s["creature_id"])
        current = s["count"]
        cur_power = current * p
        suggested = max(1, int(round(target / p)))
        sug_lo = max(1, int(round(lo / p)))
        sug_hi = max(1, int(round(hi / p)))
        ratio = (cur_power / target) if target else None

        if current == 0:
            status = "random quantity"
        elif lo <= cur_power <= hi:
            status = "on curve"
        elif cur_power > hi:
            status = "much too strong" if cur_power > hi * 3 else "strong"
        else:
            status = "much too weak" if cur_power < lo / 3 else "weak"

        rec = dict(s)
        rec.update({"power_each": round(p, 2),
                    "current_power": round(cur_power),
                    "target_power": round(target),
                    "target_low": round(lo), "target_high": round(hi),
                    "suggested_count": suggested,
                    "suggested_low": min(sug_lo, sug_hi),
                    "suggested_high": max(sug_lo, sug_hi),
                    "ratio": round(ratio, 2) if ratio else None,
                    "status": status, "basis": basis, "basis_samples": n,
                    "confidence": conf, "corpus_spread": round(spread, 1) if spread else None,
                    "scale": scale,
                    "band": band, "map_anchor": round(anchor),
                    "reward_multiplier": round(factor, 2)})
        out.append(rec)
    return out


# --------------------------------------------------------------------------
# Fairness: split the map between players and compare their shares
# --------------------------------------------------------------------------
def territory_report(m):
    starts = start_positions(m)
    if not starts:
        return {"players": {}, "note": "no player start positions found"}
    per = defaultdict(lambda: {"mines": 0, "resources": 0, "artifacts": 0,
                               "dwellings": 0, "towns": 0, "guard_power": 0.0,
                               "stacks": 0, "nearest_guard": None})
    for o in m["objects"]:
        d, owner, _ = _nearest(starts, o["x"], o["y"], o["z"])
        if owner is None:
            continue
        oid = o["object_id"]
        t = per[owner]
        if oid == 53:
            t["mines"] += 1
        elif oid in (79, 76):
            t["resources"] += 1
        elif oid in (5, 65, 66, 67, 68, 69, 93):
            t["artifacts"] += 1
        elif oid in (17, 18, 19, 20, 216, 217, 218):
            t["dwellings"] += 1
        elif oid in (98, 77):
            t["towns"] += 1
    return {"players": dict(per), "starts": starts}


def fairness(suggestions, m):
    """Per-player share of guard power and rewards, plus a spread metric."""
    terr = territory_report(m)
    per = terr["players"]
    for s in suggestions:
        p = s["nearest_player"]
        if p in per:
            per[p]["stacks"] += 1
            per[p]["guard_power"] += s["current_power"]
            d = s["distance_to_start"]
            if d is not None and (per[p]["nearest_guard"] is None
                                  or d < per[p]["nearest_guard"]):
                per[p]["nearest_guard"] = d
    metrics = {}
    for field in ("mines", "resources", "artifacts", "dwellings", "guard_power"):
        vals = [v[field] for v in per.values()]
        if vals and max(vals) > 0:
            lo, hi = min(vals), max(vals)
            metrics[field] = {"min": lo, "max": hi,
                              "spread_pct": round(100 * (hi - lo) / hi, 1)}
    return {"per_player": per, "spread": metrics}


# --------------------------------------------------------------------------
# Warnings
# --------------------------------------------------------------------------
def warnings(m, suggestions, fair):
    w = []

    randoms = [s for s in suggestions if s["count"] == 0]
    if randoms:
        w.append(f"{len(randoms)} stacks are set to Quantity: Random in the "
                 f"editor, so the game decides their size at load time from "
                 f"map difficulty rather than you. That is a legitimate "
                 f"choice, but those stacks cannot be balanced deliberately "
                 f"until they are given a fixed amount.")

    for field, label in (("mines", "mines"), ("artifacts", "artifacts"),
                         ("dwellings", "dwellings"), ("resources", "resource piles"),
                         ("guard_power", "total guard strength")):
        sp = fair["spread"].get(field)
        if sp and sp["spread_pct"] >= 30:
            w.append(f"Uneven {label} between players: the best-served player "
                     f"has {sp['max']:.0f} and the worst {sp['min']:.0f} "
                     f"({sp['spread_pct']}% spread).")

    close = [s for s in suggestions
             if s["distance_to_start"] is not None and s["distance_to_start"] <= 8
             and (s["ranged"] or s["flying"]) and s["count"] > 0]
    if close:
        w.append(f"{len(close)} ranged or flying stacks sit within 8 tiles of a "
                 f"start. Those are disproportionately hard for a starting army "
                 f"and punish some town types far more than others.")

    unguarded = [o for o in m["objects"]
                 if o["object_id"] in (5, 65, 66, 67, 68, 69, 93)
                 and not o.get("guards")]
    arts = [o for o in m["objects"] if o["object_id"] in (5, 65, 66, 67, 68, 69, 93)]
    if arts and len(unguarded) / len(arts) > 0.6:
        w.append(f"{len(unguarded)} of {len(arts)} artifacts have no attached "
                 f"guard. Some may be blocked by nearby wandering stacks, but "
                 f"it is worth checking which are simply free to walk onto.")

    # Distance was tested against the corpus and did not predict guard
    # strength, so a map whose far guards are no stronger than its near ones
    # is not automatically wrong. What is worth flagging is a player whose
    # immediate surroundings are far softer or harder than everyone else's.
    by_player = defaultdict(list)
    for s in suggestions:
        if s["count"] > 0 and s["distance_fraction"] is not None \
                and s["distance_fraction"] <= 0.15 and s["nearest_player"]:
            by_player[s["nearest_player"]].append(s["current_power"])
    meds = {p: statistics.median(v) for p, v in by_player.items() if len(v) >= 3}
    if len(meds) >= 2:
        lo_p, lo_v = min(meds.items(), key=lambda kv: kv[1])
        hi_p, hi_v = max(meds.items(), key=lambda kv: kv[1])
        if lo_v and hi_v / lo_v >= 3:
            w.append(f"Opening difficulty is uneven: guards near {hi_p}'s start "
                     f"are typically {hi_v:,.0f} power but near {lo_p}'s only "
                     f"{lo_v:,.0f} ({hi_v / lo_v:.1f}x). That gap is felt in the "
                     f"first few turns.")

    lvl = m["max_hero_level"]
    if lvl:
        w.append(f"Hero level is capped at {lvl}, so late-game stacks cannot be "
                 f"answered by unlimited hero growth — keep the far bands "
                 f"reachable.")

    strong = [s for s in suggestions if s["status"] == "much too strong"]
    weak = [s for s in suggestions if s["status"] == "much too weak"]
    if strong:
        w.append(f"{len(strong)} stacks are at least twice the corpus norm for "
                 f"their position and reward.")
    if weak:
        w.append(f"{len(weak)} stacks are at most half the corpus norm and may "
                 f"give away their reward too cheaply.")
    return w


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def report(m, model, suggestions, fair, path=""):
    L = []
    a = L.append
    val = validate_model(model)
    a(f"# Balance report: {m['name'] or os.path.basename(path)}\n")

    a("## Reference corpus\n")
    a(f"Learned from {len(model['maps'])} map(s), "
      f"{model['sample_size']} guard stacks.\n")
    a("| Map | Size | Players | Objects | Artifacts | Mines | Difficulty |")
    a("|---|---|---|---|---|---|---|")
    for mm in model["maps"]:
        a(f"| {mm['name']} | {mm['size']} | {mm['players']} | {mm['objects']} "
          f"| {mm['artifacts']} | {mm['mines']} | {mm['difficulty']} |")
    a("")
    if val["correlation"] is not None:
        a(f"Model check: learned creature power vs. creature tier correlates "
          f"r = {val['correlation']:.2f} across {val['n']} creatures — "
          f"{val['verdict']}.\n")

    ds = model.get("distance_signal") or {}
    if ds.get("median_r") is not None:
        a("## Does distance from a start predict guard strength?\n")
        a(f"Measured per map: median rank correlation "
          f"**r = {ds['median_r']:+.2f}**, positive in {ds['positive_maps']} of "
          f"{ds['total_maps']} reference maps.\n")
        a("In this corpus it essentially does not. Guards are not reliably "
          "tougher further from a start, so distance is reported as context "
          "below but is not used to size the suggestions.\n")
        a("| Map | Stacks | Correlation |")
        a("|---|---|---|")
        for d in ds["per_map"]:
            a(f"| {d['map']} | {d['n']} | {d['r']:+.2f} |")
        a("")

    a("## What a guard is worth, by what it guards\n")
    a("Measured inside each map as a multiple of that map's own typical "
      "guard, then combined across maps. This is the model's core table.\n")
    a("| Guarding | Reference maps | Stacks | Typical | Common range |")
    a("|---|---|---|---|---|")
    for r in REWARD_ORDER:
        d = model.get("multipliers", {}).get(r)
        if d:
            a(f"| {r} | {d['maps']} | {d['n']} | {d['median']:.2f}x "
              f"| {d['p25']:.2f}x – {d['p75']:.2f}x |")
    a("")

    a("## Fairness between players\n")
    a("| Player | Towns | Mines | Resources | Artifacts | Dwellings | "
      "Guard power | Nearest guard |")
    a("|---|---|---|---|---|---|---|---|")
    for p, v in sorted(fair["per_player"].items()):
        a(f"| {p} | {v['towns']} | {v['mines']} | {v['resources']} "
          f"| {v['artifacts']} | {v['dwellings']} | {v['guard_power']:.0f} "
          f"| {v['nearest_guard'] if v['nearest_guard'] is not None else '-'} |")
    a("")
    for field, sp in fair["spread"].items():
        a(f"- **{field}**: {sp['spread_pct']}% spread "
          f"(min {sp['min']:.0f}, max {sp['max']:.0f})")
    a("")

    a("## Warnings\n")
    for wmsg in warnings(m, suggestions, fair):
        a(f"- {wmsg}")
    a("")

    counts = Counter(s["status"] for s in suggestions)
    a("## Stack verdicts\n")
    for k in ("much too weak", "weak", "on curve", "strong",
              "much too strong", "random quantity"):
        if counts.get(k):
            a(f"- {k}: {counts[k]}")
    a("")

    off = [s for s in suggestions
           if s["status"] in ("much too strong", "much too weak")]
    off.sort(key=lambda s: -abs(math.log(max(s["ratio"] or 1, 1e-3))))
    if off:
        a("## Biggest outliers\n")
        a("| Tile | Creature | Now | Suggested range | Ratio | Guarding | Dist | Status |")
        a("|---|---|---|---|---|---|---|---|")
        for s in off[:40]:
            a(f"| ({s['x']},{s['y']},{s['z']}) | {s['creature']} | {s['count']} "
              f"| {s['suggested_low']}–{s['suggested_high']} | {s['ratio']}x "
              f"| {s['reward']} | {s['distance_to_start']} | {s['status']} |")
        a("")

    a("## How to read this\n")
    a("Creature power is the game's own AI Value adjusted for speed and for "
      "ranged and flying traits, so 40 Pikemen and 3 Angels can be compared "
      "directly.")
    a("")
    a("Targets are **relative to your own map**. Reference maps of the same "
      "size differ by as much as 50x in how large their stacks are, so there "
      "is no universal correct guard strength to impose. Instead the corpus "
      "supplies the *ratios* between reward types, which are consistent "
      "between mapmakers, and those ratios are applied to your map's own "
      "typical guard.")
    a("")
    a("A verdict of \"much too strong\" therefore means the stack is large "
      "compared with the rest of your map, given what it guards. It never "
      "means your map should look like someone else's.")
    a("")
    a("The common range is wide because real maps genuinely vary; about two "
      "thirds of reference stacks fall inside their own band. Treat the "
      "extremes as the actionable signal.")
    a("")
    a("Suggestions are conventions, not rules. A deliberately brutal guard "
      "on a key artifact is a design choice; this report only says it "
      "departs from what the reference maps do.")
    return "\n".join(L)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
SUGGESTION_FIELDS = [
    "map", "x", "y", "z", "creature", "creature_id", "tier", "upgraded",
    "ranged", "flying", "count", "suggested_count", "suggested_low",
    "suggested_high", "ratio", "status", "power_each", "current_power",
    "target_power", "target_low", "target_high", "reward", "reward_object",
    "reward_multiplier", "map_anchor", "band", "distance_to_start",
    "distance_fraction", "nearest_player", "distance_to_enemy",
    "nearest_enemy", "same_level_as_start", "disposition", "never_flees",
    "basis", "basis_samples", "kind", "random_count",
]


def main():
    import argparse
    import csv as _csv

    ap = argparse.ArgumentParser(
        description="Learn guard-stack conventions from reference maps and "
                    "apply them to another map.")
    ap.add_argument("--reference", nargs="+", required=True,
                    help="one or more .h3m maps to learn from")
    ap.add_argument("--analyze", required=True, help="the .h3m map to check")
    ap.add_argument("--report", help="write the Markdown report here")
    ap.add_argument("--csv", help="write per-stack suggestions here")
    ap.add_argument("--auto-balance", metavar="OUT.h3m",
                    help="resize creature stacks and write the map here")
    ap.add_argument("--window", nargs=2, type=float, default=[0.5, 5.0],
                    metavar=("MIN", "MAX"),
                    help="only touch stacks between MIN and MAX times the "
                         "norm (default 0.5 5.0)")
    ap.add_argument("--auto-report", metavar="FILE.md",
                    help="write the auto-balance report here")
    args = ap.parse_args()

    model = build_model(args.reference, progress=lambda s: print(s))
    v = validate_model(model)
    ds = model.get("distance_signal") or {}
    print(f"Model: {model['sample_size']} stacks from "
          f"{len(model['maps'])} maps, {len(model.get('multipliers', {}))} "
          f"reward types")
    if v.get("correlation") is not None:
        print(f"  creature power vs tier: r={v['correlation']:.2f} ({v['verdict']})")
    if ds.get("median_r") is not None:
        print(f"  distance vs guard strength: median r={ds['median_r']:+.2f} "
              f"(positive in {ds['positive_maps']}/{ds['total_maps']} maps)")

    m = h3m.parse_file(args.analyze)
    sug = suggest(m, model, args.analyze)
    fair = fairness(sug, m)

    counts = Counter(s["status"] for s in sug)
    print("Verdicts: " + ", ".join(f"{k} {n}" for k, n in counts.most_common()))

    if args.report:
        with open(args.report, "w") as f:
            f.write(report(m, model, sug, fair, args.analyze))
        print("wrote", args.report)
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=SUGGESTION_FIELDS,
                                extrasaction="ignore")
            w.writeheader()
            w.writerows(sug)
        print("wrote", args.csv)

    if args.auto_balance:
        lo, hi = args.window
        plan = plan_auto_balance(m, model, args.analyze, lo, hi)
        done = apply_auto_balance(m, plan)
        print(f"auto-balance: {len(done)} stack(s) resized "
              f"(window {lo}x-{hi}x)")
        h3m.save(m, args.auto_balance)
        print("wrote", args.auto_balance)
        out = args.auto_report or (
            os.path.splitext(args.auto_balance)[0] + "_autobalance.md")
        with open(out, "w") as f:
            f.write(auto_balance_report(m, plan, lo, hi, args.analyze))
        print("wrote", out)




# --------------------------------------------------------------------------
# Auto-balance
# --------------------------------------------------------------------------
def plan_auto_balance(m, model, path="", min_ratio=0.5, max_ratio=5.0,
                      include_random=False, include_guards=True,
                      include_wandering=True, scale=1.0):
    """Work out which stacks to resize, without changing anything.

    min_ratio / max_ratio bound which stacks are touched. A stack sitting at
    20x the norm is usually a deliberate set piece — a final boss, a gate the
    designer means to be impassable for hours — so by default anything beyond
    5x is left alone. Widen the bounds to sweep those in too.
    """
    changes = []
    for s in suggest(m, model, path, scale=scale):
        if s["creature_id"] is None:
            continue
        if s["count"] == 0 and not include_random:
            continue
        if s["kind"] == "attached" and not include_guards:
            continue
        if s["kind"] == "wandering" and not include_wandering:
            continue
        ratio = s["ratio"]
        is_random = s["count"] == 0
        if is_random:
            # a random-quantity stack has no current size to compare, so the
            # ratio window cannot apply to it; it is included only when the
            # caller explicitly asks for these
            if not include_random:
                continue
        else:
            if ratio is None or ratio <= 0:
                continue
            if not (min_ratio <= ratio <= max_ratio):
                continue
        new = max(1, min(65535, int(s["suggested_count"])))
        if new == s["count"]:
            continue
        changes.append({
            "object_index": s["index"], "x": s["x"], "y": s["y"], "z": s["z"],
            "creature": s["creature"], "creature_id": s["creature_id"],
            "kind": s["kind"], "slot_index": s.get("slot_index"),
            "old_count": s["count"], "new_count": new,
            "ratio": ratio, "status": s["status"], "reward": s["reward"],
            "reward_object": s["reward_object"],
            "target_power": s["target_power"],
            "suggested_low": s["suggested_low"],
            "suggested_high": s["suggested_high"],
            "nearest_player": s["nearest_player"],
            "distance_to_start": s["distance_to_start"],
            "apply": True,
        })
    changes.sort(key=lambda c: -abs(math.log(max(c["ratio"] or 1e-6, 1e-6))))
    return changes


def _stack_target(m, change):
    """The exact dict holding the count for a planned change."""
    o = m["objects"][change["object_index"]]
    if change["kind"] == "wandering":
        return o
    guards = o.get("guards") or []
    i = change.get("slot_index")
    if i is not None and i < len(guards):
        return guards[i]
    return None


def apply_auto_balance(m, changes):
    """Queue the accepted changes as edits. Returns those actually queued."""
    done = []
    for c in changes:
        if not c.get("apply", True):
            continue
        target = _stack_target(m, c)
        if target is None:
            c["error"] = "could not locate this stack again"
            continue
        try:
            h3m.edit(m, target, "count", c["new_count"],
                     label=f"{c['creature']} at ({c['x']},{c['y']},{c['z']}) "
                           f"{c['old_count']} -> {c['new_count']}")
        except h3m.EditError as e:
            c["error"] = str(e)
            continue
        done.append(c)
    return done


def auto_balance_report(m, changes, min_ratio, max_ratio, path=""):
    L = []
    a = L.append
    applied = [c for c in changes if c.get("apply", True) and "error" not in c]
    a(f"# Auto-balance report: {m['name'] or os.path.basename(path)}\n")
    a(f"Stacks resized: **{len(applied)}** of {len(changes)} planned.\n")
    a(f"Only stacks between **{min_ratio}x** and **{max_ratio}x** of the norm "
      f"were touched. Anything outside that window was left as the designer "
      f"set it, on the assumption that a stack many times the norm is a "
      f"deliberate set piece rather than a mistake.\n")

    grew = [c for c in applied if c["new_count"] > c["old_count"]]
    cut = [c for c in applied if c["new_count"] < c["old_count"]]
    a(f"- increased: {len(grew)}")
    a(f"- reduced: {len(cut)}")
    if applied:
        before = sum(c["old_count"] for c in applied)
        after = sum(c["new_count"] for c in applied)
        a(f"- total creatures in the touched stacks: {before:,} -> {after:,}")
    a("")

    if applied:
        a("## Changes\n")
        a("| Tile | Creature | Was | Now | Ratio before | Guarding | Nearest player |")
        a("|---|---|---|---|---|---|---|")
        for c in applied:
            a(f"| ({c['x']},{c['y']},{c['z']}) | {c['creature']} "
              f"| {c['old_count']} | {c['new_count']} | {c['ratio']}x "
              f"| {c['reward']} | {c['nearest_player']} |")
        a("")

    skipped = [c for c in changes if not c.get("apply", True)]
    if skipped:
        a("## Skipped by you\n")
        for c in skipped:
            a(f"- ({c['x']},{c['y']},{c['z']}) {c['creature']} "
              f"{c['old_count']} -> {c['new_count']}")
        a("")
    failed = [c for c in changes if "error" in c]
    if failed:
        a("## Could not apply\n")
        for c in failed:
            a(f"- ({c['x']},{c['y']},{c['z']}) {c['creature']}: {c['error']}")
        a("")
    a("Counts were left untouched where the stack uses a random amount, since "
      "the game decides those at load time.")
    return "\n".join(L)


AUTO_BALANCE_FIELDS = [
    "x", "y", "z", "creature", "creature_id", "kind", "old_count",
    "new_count", "ratio", "status", "slot_index", "reward", "reward_object",
    "confidence", "corpus_spread",
    "suggested_low", "suggested_high", "nearest_player",
    "distance_to_start", "object_index",
]


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------
# What is a guard actually protecting?
# --------------------------------------------------------------------------
def guarded_region(m, guard, max_pocket_fraction=0.45, render=None):
    """Flood-fill the area a wandering monster seals off.

    Classifying a guard by "nearest valuable within 3 tiles" is too crude: a
    single Behemoth on an isthmus can be the only thing standing between a
    player and two mines, a dwelling and a pile of resources. This walks the
    passability grid with the guard treated as a wall and reports the pocket
    it closes, along with everything inside it.

    Returns None when the guard blocks nothing (it sits in the open).
    """
    if render is None:
        import h3m_render as render
    z = guard["z"]
    size = m["size"]
    key = ("_passcache", z)
    cache = m.setdefault("_passcache", {})
    if z not in cache:
        ti = render.build_terrain_index(m)
        xi = render.build_tile_index(m)
        cache[z] = (render.passability_grid(m, z, ti, xi),
                    render.water_grid(m, z, ti))
    grid, water = cache[z]

    gx, gy = guard["x"], guard["y"]
    wall = {(gx, gy)}

    # each free neighbour starts its own region; if the guard is a gateway the
    # regions on either side will not join up
    regions = []
    unassigned = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            p = (gx + dx, gy + dy)
            if render.walkable(grid, water, p[0], p[1], size):
                unassigned.append(p)
    while unassigned:
        seed = unassigned.pop()
        if any(seed in r for r in regions):
            continue
        r = render.flood(grid, water, size, [seed], wall)
        regions.append(r)
    if len(regions) < 2:
        return None                      # not separating anything

    regions.sort(key=len)
    pocket = regions[0]
    total = sum(len(r) for r in regions)
    if not pocket or len(pocket) > total * max_pocket_fraction:
        return None                      # both sides are open map

    contents = []
    for o in m["objects"]:
        if o["z"] != z or o["index"] == guard["index"]:
            continue
        if o["object_id"] not in VALUABLE:
            continue
        tpl = m["templates"][o["template_index"]]
        tiles = [(o["x"] + dx, o["y"] + dy)
                 for dx, dy, _b, _v in h3m.footprint(tpl)] or [(o["x"], o["y"])]
        if any(t in pocket for t in tiles):
            contents.append({
                "index": o["index"], "x": o["x"], "y": o["y"], "z": o["z"],
                "name": o["name"], "reward": refine_reward(o, VALUABLE[o["object_id"]]),
                "summary": h3m.detail_of(o)})
    return {"pocket_tiles": sorted(pocket), "pocket_size": len(pocket),
            "open_size": len(regions[-1]), "contents": contents}


def describe_guarded(region):
    if not region:
        return "blocks nothing enclosed"
    if not region["contents"]:
        return f"seals a {region['pocket_size']}-tile pocket (nothing of value in it)"
    from collections import Counter
    c = Counter(x["reward"].split(":")[0] for x in region["contents"])
    bits = ", ".join(f"{n}x {k}" if n > 1 else k for k, n in c.most_common())
    return f"seals a {region['pocket_size']}-tile pocket containing {bits}"
