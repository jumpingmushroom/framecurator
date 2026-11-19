import pytest
import yaml

from framecurator import config

U, O, H = "http://192.0.2.10:8099", "http://192.0.2.11:11434", "http://homeassistant.local:8123"
HOME = {"lat": 59.9, "lon": 10.7}
MINIMAL = {"immich": {"url": U}, "ollama": {"url": O}, "home": HOME}


def _write(tmp_path, monkeypatch, user):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(user))


def test_minimal_config_gets_every_default(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, MINIMAL)
    cfg = config.load_config()
    assert cfg["schedule"] == {"curator_minutes": 60, "backfill_start": "00:30", "backfill_hours": 5.5}
    assert cfg["mix"]["library"] == 0.15 and cfg["exclude_albums"] == [] and cfg["ollama"]["model"] == "gemma3:4b"


def test_existing_full_config_keeps_every_user_value(tmp_path, monkeypatch):
    monkeypatch.setenv("HA_TOKEN", "x")
    full = {"immich": {"url": U}, "ha": {"url": H}, "home": {"radius_m": 300}, "ollama": {"url": O, "model": "m", "min_score": 7},
            "exclude_albums": ["X"], "mix": {"on_this_day": 0.3, "favorites_picks": 0.2, "recent_30d": 0.35, "library": 0.30},
            "frame": {"port": 8099, "rotate_minutes": 15, "image_size": "preview", "pool_ttl_minutes": 5}}
    _write(tmp_path, monkeypatch, full)
    cfg = config.load_config()
    assert cfg["exclude_albums"] == ["X"] and cfg["mix"]["library"] == 0.30 and cfg["schedule"]["backfill_hours"] == 5.5
    assert cfg["ollama"]["model"] == "m" and cfg["ollama"]["min_score"] == 7


@pytest.mark.parametrize("user,needle", [
    ({"ollama": {"url": O}, "home": HOME}, "immich.url"),
    ({"immich": {"url": U}, "home": HOME}, "ollama.url"),
    ({"immich": {"url": U}, "ollama": {"url": O}}, "home.lat"),
    (MINIMAL | {"schedule": {"backfill_start": "25:00"}}, "backfill_start"),
    (MINIMAL | {"schedule": {"backfill_hours": 24}}, "backfill_hours"),
])
def test_missing_or_bad_settings_stop_with_one_sentence(user, needle, monkeypatch):
    monkeypatch.delenv("HA_TOKEN", raising=False)
    with pytest.raises(SystemExit, match=needle):
        config.check(config.merge(config.DEFAULTS, user))


def test_merge_replaces_lists_and_recurses_dicts():
    assert config.merge({"a": {"b": 1, "c": 2}, "l": [1]}, {"a": {"b": 3}, "l": [2]}) == {"a": {"b": 3, "c": 2}, "l": [2]}


def test_empty_schedule_section_keeps_defaults(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, MINIMAL | {"schedule": None})
    assert config.load_config()["schedule"]["backfill_hours"] == 5.5


def test_empty_home_section_gives_clear_error(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"immich": {"url": U}, "ollama": {"url": O}, "home": None})
    with pytest.raises(SystemExit, match="home.lat"):
        config.load_config()


def test_ha_url_without_token_loads_and_only_home_coords_needs_the_token(tmp_path, monkeypatch):
    from framecurator import immich

    _write(tmp_path, monkeypatch, {"immich": {"url": U}, "ollama": {"url": O}, "ha": {"url": H}})
    monkeypatch.delenv("HA_TOKEN", raising=False)
    cfg = config.load_config()  # the frame service has no HA_TOKEN and must still start
    with pytest.raises(SystemExit, match="HA_TOKEN"):
        immich.home_coords(cfg)


def test_backfill_start_error_says_to_quote_it():
    with pytest.raises(SystemExit, match='in quotes'):
        config.check(config.merge(config.DEFAULTS, MINIMAL | {"schedule": {"backfill_start": "25:00"}}))
