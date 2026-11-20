"""Choose the next photo from the curated pool. Pure: no network, no clock."""
import random
from datetime import datetime

MODES = {"mixed": None, "recent": "recent_30d", "picks": "favorites_picks", "memories": "on_this_day"}


def taken(asset):
    return datetime.fromisoformat(asset["localDateTime"])


def in_bucket(name, asset, picks, now):
    t = taken(asset)
    if name == "on_this_day":
        # shortcut: month/day within 3 days, ignoring year-end wraparound; fine for a photo frame
        try:
            this_year = t.replace(year=now.year)
        except ValueError:  # 29 February in a non-leap year
            this_year = t.replace(year=now.year, day=28)
        return t.year < now.year and abs((this_year - now.replace(tzinfo=t.tzinfo)).days) <= 3
    if name == "favorites_picks":
        return bool(asset.get("isFavorite")) or asset["id"] in picks
    if name == "recent_30d":
        return (now.replace(tzinfo=t.tzinfo) - t).days <= 30
    return True  # library


def pick(assets, shown, picks, mix, mode, now, rng=random):
    """assets: curated pool; shown: ids shown within the repeat window; mix: bucket weights."""
    pool = [a for a in assets if a["id"] not in shown] or list(assets)  # everything seen lately: allow repeats
    if not pool:
        return None
    buckets = {n: [a for a in pool if in_bucket(n, a, picks, now)] for n in mix}
    buckets["library"] = pool
    if MODES.get(mode):
        name = MODES[mode] if buckets[MODES[mode]] else "library"
    else:
        live = {n: w for n, w in mix.items() if buckets[n] and w > 0}
        name = rng.choices(list(live), list(live.values()))[0] if live else "library"  # all weights zero: whole pool
    return rng.choice(buckets[name]), name
