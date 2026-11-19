"""Config loading: built-in defaults under config.yaml, with clear errors for missing settings."""
import copy
import os
import re
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("FRAMECURATOR_HOME") or Path(__file__).resolve().parents[2])

DEFAULTS = {
    "home": {"radius_m": 300},
    "ollama": {"model": "gemma3:4b", "min_score": 6},
    "travel_km": 30,
    "exclude_albums": [],
    "picks_album": "Frame - Picks",
    "window_days": 60,
    "data_dir": "data",
    "display": {"width": 1920, "height": 1200},
    "mix": {"on_this_day": 0.30, "favorites_picks": 0.20, "recent_30d": 0.35, "library": 0.15},
    "repeat_days": 14,
    "screenshot_name": r"(?i)screenshot|screen_shot|^IMG_\d+\.(png|webp)$|\.png$",
    "ocr_keywords": ["receipt", "invoice", "subtotal", "total", "vat", "order number", "tracking"],
    "frame": {"port": 8099, "rotate_minutes": 15, "image_size": "preview", "pool_ttl_minutes": 5},
    "schedule": {"curator_minutes": 60, "backfill_start": "00:30", "backfill_hours": 5.5},
}


def merge(defaults, user):
    """Recursive for dicts, user wins; lists and scalars are replaced."""
    out = copy.deepcopy(defaults)
    for k, v in (user or {}).items():
        if v is None and isinstance(out.get(k), dict):
            continue  # an empty YAML section keeps its defaults
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def check(cfg):
    for key, section in (("immich.url", "immich"), ("ollama.url", "ollama")):
        if not (cfg.get(section) or {}).get("url"):
            raise SystemExit(f"Set {key} in config.yaml.")
    home, ha = cfg["home"], cfg.get("ha") or {}
    if (home.get("lat") is None or home.get("lon") is None) and not ha.get("url"):
        raise SystemExit("Set home.lat and home.lon in config.yaml, or ha.url plus the HA_TOKEN environment variable.")
    s = cfg["schedule"]
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(s["backfill_start"]))
    if not m:
        raise SystemExit("Set schedule.backfill_start in config.yaml as HH:MM in quotes, e.g. \"00:30\".")
    if not isinstance(s["backfill_hours"], (int, float)) or not 0 <= s["backfill_hours"] <= 23.5:
        raise SystemExit("Set schedule.backfill_hours in config.yaml to a number from 0 to 23.5.")


def load_config():
    env = ROOT / ".env"  # in the container the variables come from the environment instead
    for line in env.read_text().splitlines() if env.exists() else []:
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    cfg = merge(DEFAULTS, yaml.safe_load((ROOT / "config.yaml").read_text()))
    check(cfg)
    return cfg
