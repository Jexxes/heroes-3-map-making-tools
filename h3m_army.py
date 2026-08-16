"""
h3m_army.py — work out how many of each creature to put in a stack.

Given a set of creatures and a target (total hit points, or total combat
power), this produces counts that look like an army rather than a pile: the
ratio between tiers follows weekly growth, which is the game's own statement
of how common each creature is meant to be.

Without that, asking for "10,000 HP of Peasants, Boars and Azure Dragons"
gives you ten thousand Peasants, which is both absurd to fight and trivially
different in power from the same HP spent on dragons.
"""

import h3m
import h3m_creatures as creatures

METRICS = ("hp", "power", "ai_value")


def _metric(cid, metric):
    if metric == "hp":
        v = creatures.stat(cid, "hp")
    elif metric == "ai_value":
        v = creatures.ai_value(cid)
    else:
        v = creatures.power(cid)
    return float(v) if v else None


def natural_weights(creature_ids, tier_tilt=0.0):
    """tier_tilt shifts the mix: negative favours low tiers, positive high."""
    """Relative abundance of each creature, from weekly growth.

    Growth is the game's own scale of how many of a creature a player is
    expected to have, so a stack built in growth proportion reads as a normal
    army: many Pikemen, a handful of Angels.
    """
    weights = {}
    for cid in creature_ids:
        g = creatures.stat(cid, "growth")
        if not g:
            tier = creatures.stat(cid, "level") or 4
            g = max(1.0, 16.0 / max(tier, 1))     # fallback shaped like growth
        w = float(g)
        if tier_tilt:
            tier = creatures.stat(cid, "level") or 4
            # tilt +1 roughly doubles each tier step's share, -1 halves it
            w *= 2.0 ** (tier_tilt * (tier - 4) / 2.0)
        weights[cid] = w
    total = sum(weights.values()) or 1.0
    return {cid: w / total for cid, w in weights.items()}


def compose(creature_ids, target, metric="hp", weights=None, max_slots=7,
            min_each=1, cap=65535, tier_tilt=0.0):
    """Counts for each creature so the stack totals roughly `target`.

    Returns a dict with the counts and what they actually add up to.
    """
    # positions, not creature ids: a garrison may legitimately hold the same
    # creature in two slots, and keying by id would merge them
    slots_in = [(i, c) for i, c in enumerate(creature_ids)
                if c is not None and _metric(c, metric)][:max_slots]
    ids = [c for _i, c in slots_in]
    if not slots_in or target <= 0:
        return {"counts": {}, "achieved": 0.0, "target": target,
                "error_pct": None, "metric": metric, "slots": []}

    base_w = weights or natural_weights(ids, tier_tilt)
    # a creature occupying two slots shares its weight between them
    occurrences = {}
    for _i, c in slots_in:
        occurrences[c] = occurrences.get(c, 0) + 1
    w = {i: base_w[c] / occurrences[c] for i, c in slots_in}
    per_unit = {i: _metric(c, metric) for i, c in slots_in}

    # one "bundle" is a growth-proportioned mix; scale bundles to hit target
    bundle = sum(w[i] * per_unit[i] for i, _c in slots_in)
    k = target / bundle if bundle else 0
    counts = {i: max(min_each, min(cap, int(round(k * w[i]))))
              for i, _c in slots_in}

    def total():
        return sum(counts[i] * per_unit[i] for i, _c in slots_in)

    # greedy refinement: nudge whichever slot closes the gap best
    for _ in range(600):
        err = target - total()
        if abs(err) <= 1e-9:
            break
        best, best_gap = None, abs(err)
        for i, _c in slots_in:
            step = 1 if err > 0 else -1
            if counts[i] + step < min_each or counts[i] + step > cap:
                continue
            gap = abs(err - step * per_unit[i])
            if gap < best_gap - 1e-9:
                best, best_gap = i, gap
        if best is None:
            break
        counts[best] += 1 if err > 0 else -1

    achieved = total()
    slots = []
    for i, c in slots_in:
        slots.append({
            "slot": i,
            "creature_id": c, "creature": h3m.cname(c), "count": counts[i],
            "tier": creatures.stat(c, "level"),
            "hp_each": creatures.stat(c, "hp"),
            "power_each": creatures.power(c),
            "total_hp": (creatures.stat(c, "hp") or 0) * counts[i],
            "total_power": (creatures.power(c) or 0) * counts[i],
            "ranged": c in creatures.RANGED, "flying": c in creatures.FLYING,
        })
    return {
        "counts": counts, "slots": slots, "metric": metric,
        "target": target, "achieved": achieved,
        "error_pct": (achieved - target) / target * 100 if target else None,
        "total_hp": sum(s["total_hp"] for s in slots),
        "total_power": sum(s["total_power"] for s in slots),
        "creatures": sum(s["count"] for s in slots),
    }


def norm_target(m, model, reward="garrison", metric="power", scale=1.0):
    """A target drawn from the map's own norms, so a filled garrison sits
    where the balance model says a guard of that kind belongs."""
    import h3m_balance as balance
    stacks = balance.extract_stacks(m)
    mults = model.get("multipliers", {}) if model else {}
    implied = []
    for s in stacks:
        if s["count"] > 0 and s["creature_id"] is not None:
            f = mults.get(s["reward"], {}).get("median", 1.0) or 1.0
            implied.append(s["count"] * balance.creature_power(s["creature_id"]) / f)
    if not implied:
        return None
    import statistics
    anchor = statistics.median(implied)
    factor = mults.get(reward, {}).get("median", 1.0) or 1.0
    power_target = anchor * factor * scale
    if metric == "power":
        return power_target
    # convert a power target into an equivalent hit-point target using the
    # power-per-hit-point of an average mid-tier creature
    ref = [cid for cid in range(112)
           if creatures.stat(cid, "hp") and creatures.power(cid)]
    ratios = [creatures.power(c) / creatures.stat(c, "hp") for c in ref]
    ratios.sort()
    mid = ratios[len(ratios) // 2]
    return power_target / mid if mid else None


def describe(result):
    """One readable line per slot plus a summary."""
    if not result["slots"]:
        return "nothing to compose"
    lines = []
    for s in result["slots"]:
        tags = " ".join(t for t, on in (("ranged", s["ranged"]),
                                        ("flying", s["flying"])) if on)
        lines.append(f"{s['count']:>6} x {s['creature']:<20} "
                     f"tier {s['tier'] or '?'}  "
                     f"{s['total_hp']:>8,} hp  {s['total_power']:>10,.0f} power"
                     + (f"  [{tags}]" if tags else ""))
    lines.append(f"{'':>6}   {'TOTAL':<20}       "
                 f"{result['total_hp']:>8,} hp  {result['total_power']:>10,.0f} power")
    if result["error_pct"] is not None:
        lines.append(f"target {result['target']:,.0f} {result['metric']}, "
                     f"achieved {result['achieved']:,.0f} "
                     f"({result['error_pct']:+.2f}%)")
    return "\n".join(lines)
