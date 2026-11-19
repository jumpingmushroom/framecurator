"""Cheap metadata verdicts. Pure functions: no network."""
import math
import re

KEPT, DROPPED = "kept", "dropped"


def km_between(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def distance_km(asset, home):
    exif = asset.get("exifInfo") or {}
    if exif.get("latitude") is None or exif.get("longitude") is None:
        return None
    return km_between(exif["latitude"], exif["longitude"], home[0], home[1])


def metadata_verdict(asset, cfg, home, excluded_ids, pick_ids, ocr_hits):
    """Return (verdict, reason), or None when the photo should go on to CLIP. First match wins."""
    exif = asset.get("exifInfo") or {}
    if asset.get("isTrashed") or asset.get("isArchived") or asset.get("isOffline") or asset.get("visibility") != "timeline":
        return DROPPED, "hidden/archived/trashed"
    if asset["id"] in excluded_ids:
        return DROPPED, "in excluded album"
    if re.search(cfg["screenshot_name"], asset.get("originalFileName") or ""):
        return DROPPED, "screenshot/download filename"
    if not exif.get("make") and not exif.get("model"):
        return DROPPED, "no camera make/model"
    if any(p.get("name") for p in asset.get("people") or []):
        return KEPT, "named person"
    if asset.get("isFavorite"):
        return KEPT, "favorite"
    if asset["id"] in pick_ids:
        return KEPT, "in picks album"
    if asset["id"] in ocr_hits:
        return DROPPED, f"ocr: {ocr_hits[asset['id']]}"
    km = distance_km(asset, home)
    if km is not None and km > cfg["travel_km"]:
        return KEPT, f"travel ({km:.0f} km from home)"
    return None
