"""Config loading and the read-only Immich/HA calls the dry run needs."""
import datetime as dt
import os
import time

import httpx

from .config import ROOT, load_config  # noqa: F401  (re-exported)

TESTED_IMMICH = {"v3.1.0"}


def home_coords(cfg):
    if cfg["home"].get("lat") is not None:
        return cfg["home"]["lat"], cfg["home"]["lon"]
    if not os.environ.get("HA_TOKEN"):
        raise SystemExit("Set the HA_TOKEN environment variable (needed to read zone.home from ha.url), or set home.lat and home.lon.")
    r = httpx.get(cfg["ha"]["url"] + "/api/states/zone.home", timeout=15,
                  headers={"Authorization": "Bearer " + os.environ["HA_TOKEN"]})
    r.raise_for_status()
    a = r.json()["attributes"]
    return a["latitude"], a["longitude"]


class Immich:
    def __init__(self, cfg, key_env="IMMICH_CURATOR_KEY"):
        self.c = httpx.Client(base_url=cfg["immich"]["url"].rstrip("/") + "/api", timeout=60,
                              headers={"x-api-key": os.environ[key_env]})
        days = cfg["window_days"]
        self.after = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).isoformat()

    def check_version(self, log=print):
        """Return the server version, warning when it is not a tested one; never raises."""
        try:
            r = self.c.get("/server/version")
            r.raise_for_status()
            d = r.json()
            v = f"v{d['major']}.{d['minor']}.{d['patch']}" + (f"-{d['prerelease']}" if d.get("prerelease") else "")
        except Exception as e:  # noqa: BLE001  (a startup check must never raise)
            log(f"could not read the Immich version: {e}")
            return None
        if v not in TESTED_IMMICH:
            log(f"Immich {v} has not been tested; tested: {', '.join(sorted(TESTED_IMMICH))}")
        return v

    def _get(self, path):
        """JSON of a GET; a rejected key or server error raises instead of being parsed as data."""
        r = self.c.get(path)
        r.raise_for_status()
        return r.json()

    def _search(self, kind, body):
        r = self.c.post(f"/search/{kind}", json={"type": "IMAGE", "takenAfter": self.after, **body})
        r.raise_for_status()
        return r.json()["assets"]

    def assets(self):
        out, page = [], 1
        while page:
            res = self._search("metadata", {"size": 1000, "page": page, "withExif": True, "withPeople": True})
            out += res["items"]
            page = int(res["nextPage"]) if res.get("nextPage") else 0
        return out

    def ocr_hits(self, keywords):
        """asset id -> first keyword found in its OCR text, over the whole library."""
        hits = {}
        for kw in keywords:
            page = 1
            while page:
                res = self._search("metadata", {"size": 1000, "page": page, "ocr": kw, "takenAfter": "1900-01-01T00:00:00Z"})
                for a in res["items"]:
                    hits.setdefault(a["id"], kw)
                page = int(res["nextPage"]) if res.get("nextPage") else 0
        return hits

    def old_assets(self, size=1000):
        """Photos older than the window, newest first, a page at a time, with EXIF and people."""
        page = 1
        while page:
            res = self._search("metadata", {"takenAfter": "1900-01-01T00:00:00Z", "takenBefore": self.after, "order": "desc",
                                            "size": size, "page": page, "withExif": True, "withPeople": True})
            yield res["items"]
            page = int(res["nextPage"]) if res.get("nextPage") else 0

    def album_ids(self, name):
        """Ids of the photos in an album; empty when there is no such album.

        GET /albums/{id} has no asset list on v3.1.0, so this searches by album instead."""
        album = self.album_id(name)
        ids, page = set(), 1
        while album and page:
            res = self._search("metadata", {"albumIds": [album], "size": 1000, "page": page, "takenAfter": "1900-01-01T00:00:00Z"})
            ids |= {a["id"] for a in res["items"]}
            page = int(res["nextPage"]) if res.get("nextPage") else 0
        return ids

    def thumb(self, asset_id, size="thumbnail"):
        r = self.c.get(f"/assets/{asset_id}/thumbnail", params={"size": size})
        r.raise_for_status()
        return r.content

    def tag_id(self, value, create=False):
        """Id of tag `value` (e.g. "frame/yes"), or None if missing and not create."""
        for t in self._get("/tags"):
            if t["value"] == value:
                return t["id"]
        if not create:
            return None
        r = self.c.put("/tags", json={"tags": [value]})
        r.raise_for_status()
        return next(t["id"] for t in r.json() if t["value"] == value)

    def search_all(self, body):
        """All pages of a metadata search, with EXIF and people."""
        out, page = [], 1
        while page:
            res = self._search("metadata", {"size": 1000, "page": page, "withExif": True, "withPeople": True, **body})
            out += res["items"]
            page = int(res["nextPage"]) if res.get("nextPage") else 0
        return out

    def tagged_assets(self, tag_id):
        if tag_id is None:
            return []
        return self.search_all({"tagIds": [tag_id], "takenAfter": "1900-01-01T00:00:00Z"})

    def tagged_ids(self, tag_id):
        return {a["id"] for a in self.tagged_assets(tag_id)}

    def album_assets(self, name):
        for al in self._get("/albums"):
            if al["albumName"] == name:
                return self.search_all({"albumIds": [al["id"]], "takenAfter": "1900-01-01T00:00:00Z"})
        return []

    def faces(self, asset_id):
        r = self.c.get("/faces", params={"id": asset_id})
        r.raise_for_status()
        return r.json()

    def _bulk(self, method, path, ids, tolerate=("duplicate",)):
        ids = list(ids)
        for i in range(0, len(ids), 500):
            r = self.c.request(method, path, json={"ids": ids[i:i + 500]})
            r.raise_for_status()
            bad = [x for x in r.json() if x.get("error") not in (None, *tolerate)]
            if bad:
                raise RuntimeError(f"{method} {path} failed for {len(bad)} assets: {bad[0]}")

    def tag_assets(self, tag_id, ids):
        self._bulk("PUT", f"/tags/{tag_id}/assets", ids)

    def untag_assets(self, tag_id, ids):
        self._bulk("DELETE", f"/tags/{tag_id}/assets", ids, tolerate=("not_found", "no_permission_noop"))

    def settle(self, expectations, rounds=3, wait=6):
        """Re-check tag changes and re-apply any that were undone; returns True once they hold.

        Immich finishes tag changes in background jobs. When a photo's tags change twice within seconds, a job can
        write the older state back, so a change is only trusted after it has been seen again a few seconds later.
        expectations: [(tag_id, asset_ids, should_have_tag)]."""
        for _ in range(rounds):
            time.sleep(wait)
            fixes = []
            for tag_id, ids, present in expectations:
                have = self.tagged_ids(tag_id) & set(ids)
                bad = set(ids) - have if present else have
                if bad:
                    fixes.append((tag_id, bad, present))
            if not fixes:
                return True
            for tag_id, bad, present in fixes:
                (self.tag_assets if present else self.untag_assets)(tag_id, bad)
        return False

    def set_favorite(self, asset_id, on):
        self.c.put(f"/assets/{asset_id}", json={"isFavorite": on}).raise_for_status()

    def album_names(self):
        """Names of albums that hold at least one photo."""
        return sorted(al["albumName"] for al in self._get("/albums") if al.get("assetCount"))

    def album_id(self, name):
        return next((al["id"] for al in self._get("/albums") if al["albumName"] == name), None)

    def album_add(self, album_id, ids):
        self._bulk("PUT", f"/albums/{album_id}/assets", ids)

    def album_remove(self, album_id, ids):
        self._bulk("DELETE", f"/albums/{album_id}/assets", ids, tolerate=("not_found",))
