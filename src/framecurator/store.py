"""Local SQLite state: cached vision results and which photos the curator already tagged."""
import sqlite3


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)  # wait for the lock: the frame, curator and backfill share this file; no WAL, which misbehaves on Unraid's user share
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS vlm(model TEXT, asset_id TEXT, category TEXT, score INTEGER, PRIMARY KEY(model, asset_id));
            CREATE TABLE IF NOT EXISTS shown(asset_id TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP, device TEXT DEFAULT 'default');
            CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS blocked(device TEXT, asset_id TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS taste(device TEXT, asset_id TEXT, value INTEGER, at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS applied(asset_id TEXT PRIMARY KEY, verdict TEXT, reason TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP, policy TEXT DEFAULT 'both');
        """)
        # databases from before multi-device support: history and the current photo belong to "default"
        if "device" not in {r[1] for r in self.db.execute("PRAGMA table_info(shown)")}:
            self.db.execute("ALTER TABLE shown ADD COLUMN device TEXT DEFAULT 'default'")
        if "policy" not in {r[1] for r in self.db.execute("PRAGMA table_info(applied)")}:
            # 'both': a frame/yes or frame/no tag was written. 'yes_only': only keepers are tagged; rejects exist only here.
            self.db.execute("ALTER TABLE applied ADD COLUMN policy TEXT DEFAULT 'both'")
        self.db.execute("INSERT OR IGNORE INTO kv SELECT 'current:default', v FROM kv WHERE k='current'")
        self.db.execute("DELETE FROM kv WHERE k='current'")
        self.db.commit()

    def vlm(self, model, asset_id):
        row = self.db.execute("SELECT category, score FROM vlm WHERE model=? AND asset_id=?", (model, asset_id)).fetchone()
        return {"category": row[0], "score": row[1]} if row else None

    def put_vlm(self, model, asset_id, v):
        self.db.execute("INSERT OR REPLACE INTO vlm VALUES (?,?,?,?)", (model, asset_id, v["category"], v["score"]))
        self.db.commit()

    def applied_ids(self):
        return {r[0] for r in self.db.execute("SELECT asset_id FROM applied")}

    def put_applied(self, asset_id, verdict, reason, policy="both"):
        self.db.execute("INSERT OR REPLACE INTO applied(asset_id, verdict, reason, policy) VALUES (?,?,?,?)", (asset_id, verdict, reason, policy))
        self.db.commit()

    def shown_since(self, days, device="default"):
        q = "SELECT DISTINCT asset_id FROM shown WHERE device=? AND at >= datetime('now', ?)"
        return {r[0] for r in self.db.execute(q, (device, f"-{days} days"))}

    def put_shown(self, asset_id, device="default"):
        self.db.execute("INSERT INTO shown(asset_id, device) VALUES (?,?)", (asset_id, device))
        self.db.commit()

    def devices(self):
        return {r[0].split(":", 1)[1] for r in self.db.execute("SELECT k FROM kv WHERE k LIKE 'current:%'")}

    def get(self, key):
        row = self.db.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, value))
        self.db.commit()

    def put_blocked(self, asset_id, device):
        self.db.execute("INSERT INTO blocked(device, asset_id) VALUES (?,?)", (device, asset_id))
        self.db.commit()

    def pop_blocked(self, device):
        """The asset this device blocked most recently, removed from the log; None when there is none."""
        row = self.db.execute("SELECT rowid, asset_id FROM blocked WHERE device=? ORDER BY rowid DESC LIMIT 1", (device,)).fetchone()
        if row:
            self.db.execute("DELETE FROM blocked WHERE rowid=?", (row[0],))
            self.db.commit()
        return row[1] if row else None

    def has_blocked(self, device):
        return self.db.execute("SELECT 1 FROM blocked WHERE device=? LIMIT 1", (device,)).fetchone() is not None

    def put_taste(self, asset_id, device, value):
        self.db.execute("INSERT INTO taste(device, asset_id, value) VALUES (?,?,?)", (device, asset_id, value))
        self.db.commit()
