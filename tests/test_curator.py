from pathlib import Path

from framecurator.curator import write
from framecurator.store import Store


class FakeImmich:
    def __init__(self):
        self.tagged = {}

    def tag_id(self, value, create=False):
        return value

    def tag_assets(self, tag, ids):
        self.tagged.setdefault(tag, []).extend(ids)


def row(i, verdict):
    return {"asset": {"id": i}, "verdict": verdict, "reason": "r"}


def test_write_tags_and_records(tmp_path: Path):
    im, store = FakeImmich(), Store(tmp_path / "s.db")
    write(im, store, [row("a", "kept"), row("b", "dropped"), row("c", "dropped")])
    assert im.tagged == {"frame/yes": ["a"], "frame/no": ["b", "c"]}
    assert store.applied_ids() == {"a", "b", "c"}


def test_store_vlm_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "s.db")
    assert store.vlm("m", "a") is None
    store.put_vlm("m", "a", {"category": "people", "score": 8})
    assert store.vlm("m", "a") == {"category": "people", "score": 8}


def test_store_migrates_single_device_data(tmp_path: Path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)  # the schema before devices existed
    db.executescript("CREATE TABLE shown(asset_id TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP);"
                     "CREATE TABLE kv(k TEXT PRIMARY KEY, v TEXT);")
    db.execute("INSERT INTO shown(asset_id) VALUES ('a')")
    db.execute("INSERT INTO kv VALUES ('current', '{\"asset_id\": \"a\"}')")
    db.commit()
    db.close()
    store = Store(path)
    assert store.shown_since(14) == {"a"} and store.shown_since(14, "phone") == set()
    assert store.get("current:default") == '{"asset_id": "a"}' and store.get("current") is None
    assert store.devices() == {"default"}
    Store(path)  # opening again must not fail or duplicate anything
    assert store.devices() == {"default"}


def test_store_adds_the_policy_column_to_an_existing_applied_table(tmp_path: Path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE applied(asset_id TEXT PRIMARY KEY, verdict TEXT, reason TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP);")
    db.execute("INSERT INTO applied(asset_id, verdict, reason) VALUES ('a', 'frame/yes', 'r')")
    db.commit()
    db.close()
    store = Store(path)
    assert store.db.execute("SELECT policy FROM applied WHERE asset_id='a'").fetchone() == ("both",)  # existing rows are fully tagged
    store.put_applied("b", "frame/no", "r", policy="yes_only")
    assert store.db.execute("SELECT policy FROM applied WHERE asset_id='b'").fetchone() == ("yes_only",)
