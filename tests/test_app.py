import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from framecurator.frame import app as app_mod
from framecurator.frame.app import Frame, create_app
from framecurator.store import Store

CFG = {"frame": {"pool_ttl_minutes": 5, "rotate_minutes": 15, "image_size": "preview"}, "repeat_days": 14,
       "picks_album": "P", "ollama": {"min_score": 6}, "display": {"width": 64, "height": 40}, "mix": {"recent_30d": 1}}


def asset(i):
    return {"id": i, "localDateTime": "2026-10-20T10:00:00.000Z", "isFavorite": False, "people": [{"name": "Kari"}],
            "exifInfo": {"city": "Oslo", "country": "Norway"}}


class FakeIm:
    def __init__(self):
        self.blocked = []

    def album_names(self):
        return ["Holiday", "P"]

    def album_assets(self, name):
        return [asset(i) for i in getattr(self, "album", ())]

    def tag_id(self, value, create=False):
        return value

    def tagged_ids(self, tag):
        return set(self.blocked)

    def tagged_assets(self, tag):
        return [asset("a"), asset("b")]

    def tag_assets(self, tag, ids):
        self.blocked += ids

    def untag_assets(self, tag, ids):
        self.blocked = [i for i in self.blocked if i not in ids]
        self.untagged = list(ids)

    def set_favorite(self, asset_id, on):
        self.favorite = (asset_id, on)

    def album_id(self, name):
        return None if getattr(self, "no_album", False) else "album-1"

    def album_add(self, album, ids):
        self.album = getattr(self, "album", set()) | set(ids)

    def album_remove(self, album, ids):
        self.album = getattr(self, "album", set()) - set(ids)

    def thumb(self, aid, size):
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (300, 200), "green").save(buf, "JPEG")
        return buf.getvalue()

    def faces(self, aid):
        return []


def client(tmp_path):
    im = FakeIm()
    return TestClient(create_app(Frame(CFG, im, Store(tmp_path / "s.db")), "t" * 24)), im


H = {"Authorization": "Bearer " + "t" * 24}


def test_auth_required(tmp_path):
    c, _ = client(tmp_path)
    assert c.get("/healthz").status_code == 200
    for path in ("/state", "/image.jpg"):
        assert c.get(path).status_code == 401
        assert c.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.post("/next").status_code == 401


def test_state_image_next_and_block(tmp_path):
    c, im = client(tmp_path)
    s = c.get("/state", headers=H).json()
    assert s["place"] == s["location"] == "Oslo, Norway" and s["people"] == ["Kari"] and s["date"] == "2026-10-20"
    assert s["captured_at"] == "2026-10-20T10:00:00+00:00"  # timezone-aware ISO 8601
    assert datetime.fromisoformat(s["captured_at"]).tzinfo is not None
    assert c.get("/state", headers=H).json()["asset_id"] == s["asset_id"]  # stable until rotation
    assert c.get("/image.jpg", headers=H).headers["content-type"] == "image/jpeg"
    nxt = c.post("/next", headers=H).json()
    assert nxt["asset_id"] != s["asset_id"]  # the other photo, since the first was just shown
    blocked = c.post("/block", headers=H).json()
    assert im.blocked == [nxt["asset_id"]]
    assert blocked["asset_id"] != nxt["asset_id"]


def test_mode_validation(tmp_path):
    c, _ = client(tmp_path)
    assert c.post("/mode", headers=H, json={"mode": "bogus"}).status_code == 422
    assert c.post("/mode", headers=H, json={"mode": "recent"}).json()["mode"] == "recent"


def test_place_fallbacks(tmp_path: Path):
    frame = Frame(CFG, FakeIm(), Store(tmp_path / "s2.db"))
    cases = (({"city": "Oslo", "country": "Norway"}, "Oslo, Norway"), ({"country": "Norway"}, "Norway"),
             ({"city": "Oslo"}, "Oslo"), ({"state": "Vestfold"}, None), ({}, None))
    for exif, expected in cases:
        a = asset("x")
        a["exifInfo"] = exif
        frame.pool = {"x": a}
        m = frame.meta({"asset_id": "x", "since": 0, "mode": "mixed", "bucket": "b"})
        assert m["place"] == m["location"] == expected  # None, never ""


def test_captured_at_gets_a_timezone_when_naive(tmp_path: Path):
    frame = Frame(CFG, FakeIm(), Store(tmp_path / "s3.db"))
    a = asset("x")
    a["localDateTime"] = "2026-10-08T14:09:18"
    frame.pool = {"x": a}
    m = frame.meta({"asset_id": "x", "since": 0, "mode": "mixed", "bucket": "b"})
    assert m["captured_at"] == "2026-10-08T14:09:18+00:00" and m["date"] == "2026-10-08"


def test_devices_are_independent(tmp_path: Path):
    c, _ = client(tmp_path)
    wall, phone = {"device": "wall"}, {"device": "phone"}
    c.post("/mode", headers=H, params=wall, json={"mode": "recent"})
    assert c.get("/state", headers=H, params=wall).json()["mode"] == "recent"
    assert c.get("/state", headers=H, params=phone).json()["mode"] == "mixed"  # untouched
    assert c.get("/state", headers=H).json()["mode"] == "mixed"  # "default" device too
    first = c.get("/state", headers=H, params=phone).json()["asset_id"]
    assert c.post("/next", headers=H, params=phone).json()["asset_id"] != first
    # history is per device: "wall" has not seen what "phone" skipped, so it may show it
    shown_wall = c.get("/state", headers=H, params=wall).json()["asset_id"]
    assert c.post("/next", headers=H, params=wall).json()["asset_id"] != shown_wall


def test_device_and_size_validation(tmp_path):
    c, _ = client(tmp_path)
    for bad in ({"device": "Bad Name"}, {"device": "x" * 33}, {"device": "../etc"}):
        assert c.get("/state", headers=H, params=bad).status_code == 422
    for bad in ({"w": 10, "h": 800}, {"w": 800, "h": 99999}):
        assert c.get("/image.jpg", headers=H, params=bad).status_code == 422


def test_image_renders_at_the_requested_size(tmp_path):
    import io

    from PIL import Image

    c, _ = client(tmp_path)
    r = c.get("/image.jpg", headers=H, params={"device": "phone", "w": 800, "h": 1280})
    assert Image.open(io.BytesIO(r.content)).size == (800, 1280)
    assert Image.open(io.BytesIO(c.get("/image.jpg", headers=H).content)).size == (64, 40)  # configured default


def test_device_limit(tmp_path):
    c, _ = client(tmp_path)
    for i in range(16):
        assert c.get("/state", headers=H, params={"device": f"d{i}"}).status_code == 200
    assert c.get("/state", headers=H, params={"device": "one-too-many"}).status_code == 422
    assert c.get("/state", headers=H, params={"device": "d3"}).status_code == 200  # existing ones keep working


def test_caption_and_next_change(tmp_path: Path):
    frame = Frame(CFG, FakeIm(), Store(tmp_path / "s4.db"))
    a = asset("x")
    a["localDateTime"] = "2023-10-03T10:00:00.000Z"
    frame.pool = {"x": a}

    def meta(bucket, since=1000.0):
        return frame.meta({"asset_id": "x", "since": since, "mode": "mixed", "bucket": bucket})

    assert meta("on_this_day")["caption"] == f"Oslo, Norway · {datetime.now().year - 2023} years ago"
    assert meta("recent_30d")["caption"] == "Oslo, Norway · 3 Oct 2023"
    assert meta("library", since=1000.0)["next_change_at"] == "1970-01-01T00:31:40+00:00"  # +15 min
    a["exifInfo"] = {}
    assert meta("library")["caption"] == "3 Oct 2023"  # no place: just the date


def post(c, path, body=None, device="default"):
    return c.post(path, headers=H, params={"device": device}, json=body)


def test_previous_steps_back_and_runs_out(tmp_path):
    c, _ = client(tmp_path)
    first = c.get("/state", headers=H).json()["asset_id"]
    assert post(c, "/previous").status_code == 409  # nothing before the first photo
    second = post(c, "/next").json()
    assert second["can_go_back"] is True
    back = post(c, "/previous").json()
    assert back["asset_id"] == first and back["bucket"] == "previous"
    assert post(c, "/previous").status_code == 409  # the back stack is empty again


def test_pause_holds_the_photo_and_resume_restarts_the_countdown(tmp_path):
    c, _ = client(tmp_path)
    store = Store(tmp_path / "s.db")
    shown = c.get("/state", headers=H).json()["asset_id"]
    paused = post(c, "/pause", {"on": True}).json()
    assert paused["paused"] is True and paused["next_change_at"] is None
    stale = json.loads(store.get("current:default"))
    stale["since"] = 1.0  # long overdue
    store.put("current:default", json.dumps(stale))
    assert c.get("/state", headers=H).json()["asset_id"] == shown  # paused: no rotation
    resumed = post(c, "/pause", {"on": False}).json()
    assert resumed["asset_id"] == shown and resumed["next_change_at"] is not None  # countdown restarted, not overdue


def test_interval_changes_next_change_and_is_bounded(tmp_path):
    c, _ = client(tmp_path)
    m = post(c, "/interval", {"minutes": 5}).json()
    assert m["interval_minutes"] == 5
    assert datetime.fromisoformat(m["next_change_at"]) - datetime.fromisoformat(m["changed_at"]) == timedelta(minutes=5)
    for bad in (0, 1441):
        assert post(c, "/interval", {"minutes": bad}).status_code == 422
    assert post(c, "/interval", {"minutes": 7}, device="phone").json()["interval_minutes"] == 7
    assert c.get("/state", headers=H).json()["interval_minutes"] == 5  # per device


def test_undo_block_restores_the_photo(tmp_path):
    c, im = client(tmp_path)
    assert post(c, "/undo-block").status_code == 409
    blocked_id = c.get("/state", headers=H).json()["asset_id"]
    after = post(c, "/block").json()
    assert after["asset_id"] != blocked_id and after["can_undo"] is True
    back = post(c, "/undo-block").json()
    assert back["asset_id"] == blocked_id and im.blocked == [] and back["can_undo"] is False
    assert post(c, "/undo-block").status_code == 409
    assert post(c, "/undo-block", device="phone").status_code == 409  # undo only covers this device's own blocks


def test_favorite_and_pick_toggle(tmp_path):
    c, im = client(tmp_path)
    cur = c.get("/state", headers=H).json()
    assert cur["is_favorite"] is False and cur["is_pick"] is False
    fav = post(c, "/favorite", {"on": True}).json()
    assert fav["is_favorite"] is True and im.favorite == (cur["asset_id"], True)
    assert post(c, "/favorite", {"on": False}).json()["is_favorite"] is False
    assert post(c, "/pick", {"on": True}).json()["is_pick"] is True and im.album == {cur["asset_id"]}
    assert post(c, "/pick", {"on": False}).json()["is_pick"] is False and im.album == set()
    im.no_album = True
    assert post(c, "/pick", {"on": True}).status_code == 409  # the album must exist; the frame never creates it


def test_feedback_is_recorded_and_validated(tmp_path):
    c, _ = client(tmp_path)
    cur = c.get("/state", headers=H).json()["asset_id"]
    assert post(c, "/feedback", {"value": -1}).status_code == 200
    rows = Store(tmp_path / "s.db").db.execute("SELECT device, asset_id, value FROM taste").fetchall()
    assert rows == [("default", cur, -1)]
    for bad in (0, 2):
        assert post(c, "/feedback", {"value": bad}).status_code == 422


class RichIm(FakeIm):
    """A pool with people, places and favorites, to exercise the filter modes."""

    def tagged_assets(self, tag):
        def a(i, people=(), fav=False, exif=None):
            x = asset(i)
            x["people"], x["isFavorite"], x["exifInfo"] = [{"name": n} for n in people], fav, exif or {"city": "Oslo", "country": "Norway"}
            return x
        return [a("kari1", ["Kari"], exif={"city": "Bergen", "country": "Norway"}), a("kari2", ["Kari", "Ola"]),
                a("fav1", fav=True, exif={"city": "Paris", "country": "France"}), a("plain", exif={"country": "Sweden"})]

    def album_assets(self, name):
        return [asset("kari1"), asset("plain")] if name == "Holiday" else []


def rich(tmp_path):
    im = RichIm()
    return TestClient(create_app(Frame(CFG, im, Store(tmp_path / "s.db")), "t" * 24)), im


def shown_ids(c, device="default", n=8):
    return {post(c, "/next", device=device).json()["asset_id"] for _ in range(n)}


def test_options_list_people_albums_and_places(tmp_path):
    c, _ = rich(tmp_path)
    o = c.get("/options", headers=H).json()
    assert o["people"] == ["Kari", "Ola"]  # most photos first
    assert o["albums"] == ["Holiday", "P"]
    assert o["places"] == ["France", "Norway", "Sweden", "Bergen, Norway", "Oslo, Norway", "Paris, France"]  # countries, then cities
    assert c.get("/options").status_code == 401


def test_person_filter_only_shows_that_person_and_can_be_refused(tmp_path):
    c, _ = rich(tmp_path)
    m = post(c, "/filter", {"kind": "person", "value": "Kari"}).json()
    assert m["mode"] == "person" and m["person"] == "Kari"
    assert shown_ids(c) <= {"kari1", "kari2"}
    assert post(c, "/filter", {"kind": "person", "value": "Nobody"}).status_code == 409
    assert c.get("/state", headers=H).json()["person"] == "Kari"  # a refused choice changes nothing
    assert post(c, "/filter", {"kind": "color", "value": "x"}).status_code == 422


def test_place_album_and_favorites_modes(tmp_path):
    c, _ = rich(tmp_path)
    post(c, "/filter", {"kind": "place", "value": "Norway"})  # a country matches all its cities
    assert shown_ids(c) <= {"kari1", "kari2"}
    post(c, "/filter", {"kind": "place", "value": "Paris, France"})
    assert shown_ids(c) == {"fav1"}
    post(c, "/filter", {"kind": "album", "value": "Holiday"})
    assert shown_ids(c) <= {"kari1", "plain"}
    assert post(c, "/mode", {"mode": "favorites"}).json()["mode"] == "favorites"
    assert shown_ids(c) == {"fav1"}


def test_filter_modes_need_a_value_and_matches(tmp_path):
    c, _ = client(tmp_path)  # the plain pool has no favorites and no people
    assert post(c, "/mode", {"mode": "person"}).status_code == 409  # "choose a person first"
    assert post(c, "/mode", {"mode": "favorites"}).status_code == 409  # none match
    assert post(c, "/mode", {"mode": "recent"}).status_code == 200


def test_a_filter_that_stops_matching_falls_back_to_the_whole_pool(tmp_path):
    c, _ = rich(tmp_path)
    post(c, "/filter", {"kind": "person", "value": "Kari"})
    store = Store(tmp_path / "s.db")
    st = json.loads(store.get("current:default"))
    st["person"], st["since"] = "Gone", 1.0  # the person no longer matches anything, and a rotation is due
    store.put("current:default", json.dumps(st))
    r = c.get("/state", headers=H)
    assert r.status_code == 200 and r.json()["asset_id"] in {"kari1", "kari2", "fav1", "plain"}


def test_mix_and_repeat_settings_are_per_device_and_validated(tmp_path):
    c, _ = client(tmp_path)
    m = post(c, "/settings", {"mix": {"recent_30d": 0}, "repeat_days": 3}).json()
    assert m["mix"] == {"recent_30d": 0} and m["repeat_days"] == 3  # percentages; the test config only has this bucket
    assert c.get("/state", headers=H, params={"device": "phone"}).json()["mix"] == {"recent_30d": 100}  # config 1.0 -> 100%
    assert c.get("/state", headers=H, params={"device": "phone"}).json()["repeat_days"] == 14  # config default
    assert post(c, "/settings", {"mix": {"bogus": 1}}).status_code == 422
    assert post(c, "/settings", {"mix": {"recent_30d": 101}}).status_code == 422
    assert post(c, "/settings", {"repeat_days": -1}).status_code == 422


def test_min_score_is_global_and_bounded(tmp_path):
    c, _ = client(tmp_path)
    assert c.get("/state", headers=H).json()["min_score"] == 6
    assert post(c, "/min-score", {"value": 8}).json()["min_score"] == 8
    assert c.get("/state", headers=H, params={"device": "phone"}).json()["min_score"] == 8
    assert Store(tmp_path / "s.db").get("min_score") == "8"  # where the curator reads it
    for bad in (0, 11):
        assert post(c, "/min-score", {"value": bad}).status_code == 422


class TagIm(FakeIm):
    def __init__(self):
        super().__init__()
        self.tags = {"frame/yes": set(), "frame/no": set(), "frame/block": set()}
        self.settle_calls = []

    def settle(self, expectations, **kw):
        self.settle_calls.append(expectations)
        return True

    def tagged_ids(self, tag):
        return set(self.tags[tag])

    def tag_assets(self, tag, ids):
        self.tags[tag] |= set(ids)

    def untag_assets(self, tag, ids):
        self.tags[tag] -= set(ids)


def test_reevaluate_moves_only_score_decided_photos_that_were_not_edited(tmp_path):
    store, im = Store(tmp_path / "s.db"), TagIm()
    frame = Frame(CFG, im, store)
    applied = {"low": ("frame/yes", "vlm: event 6"),       # kept at 6, drops when the bar is 8
               "high": ("frame/no", "vlm: landscape 7"),    # dropped at 8 ... but raised to keep below
               "junk": ("frame/no", "vlm: product 2"),      # junk never becomes yes
               "rule": ("frame/yes", "named person (vlm: people 5)"),  # decided by a rule, untouched
               "edited": ("frame/yes", "vlm: event 6"),     # the user moved it by hand
               "blocked": ("frame/yes", "vlm: event 6")}
    for aid, (verdict, reason) in applied.items():
        store.put_applied(aid, verdict, reason)
        im.tags[verdict].add(aid)
    im.tags["frame/yes"].discard("edited"); im.tags["frame/no"].add("edited")  # hand edit: tag differs from the record
    im.tags["frame/block"].add("blocked")
    store.put("min_score", "8")
    r = frame.reevaluate()
    assert r == {"min_score": 8, "moved_to_yes": 0, "moved_to_no": 1, "left_alone": 2, "settled": True}
    assert im.settle_calls == [[("frame/no", ["low"], True), ("frame/yes", ["low"], False)]]  # verified after the move
    assert "low" in im.tags["frame/no"] and "low" not in im.tags["frame/yes"]
    assert "rule" in im.tags["frame/yes"] and "edited" in im.tags["frame/no"] and "blocked" in im.tags["frame/yes"]
    assert store.db.execute("SELECT verdict FROM applied WHERE asset_id='low'").fetchone()[0] == "frame/no"
    store.put("min_score", "5")  # lowering the bar lifts "high" (7) and the one just dropped (6)
    r = frame.reevaluate()
    assert r["moved_to_yes"] == 2 and {"low", "high"} <= im.tags["frame/yes"] and "junk" in im.tags["frame/no"]
    assert frame.reevaluate()["moved_to_yes"] == 0  # idempotent
    assert len(im.settle_calls) == 2  # nothing moved on the last run, so nothing to verify


def test_reevaluate_handles_backfilled_photos_whose_rejects_have_no_tag(tmp_path):
    store, im = Store(tmp_path / "s.db"), TagIm()
    frame = Frame(CFG, im, store)
    rows = {"promote": ("frame/no", "vlm: event 7"),      # a reject with no tag; the bar is lowered below, so it becomes a keeper
            "demote": ("frame/yes", "vlm: event 5"),      # a keeper below the new bar: loses its tag, gets no frame/no
            "stays": ("frame/no", "vlm: event 2"),        # still a reject: nothing to do
            "handtagged": ("frame/no", "vlm: event 7")}   # the user tagged this reject frame/yes by hand: left alone
    for aid, (verdict, reason) in rows.items():
        store.put_applied(aid, verdict, reason, policy="yes_only")
    im.tags["frame/yes"] |= {"demote", "handtagged"}
    store.put("min_score", "6")
    r = frame.reevaluate()
    assert r["moved_to_yes"] == 1 and r["moved_to_no"] == 1 and r["left_alone"] == 1
    assert im.tags["frame/yes"] == {"promote", "handtagged"}
    assert im.tags["frame/no"] == set()  # yes_only photos never get a frame/no tag
    verdicts = {a: (v, p) for a, v, p in store.db.execute("SELECT asset_id, verdict, policy FROM applied")}
    assert verdicts["promote"] == ("frame/yes", "yes_only") and verdicts["demote"] == ("frame/no", "yes_only")
    assert im.settle_calls == [[("frame/yes", ["promote"], True), ("frame/yes", ["demote"], False)]]  # one combined check


VIEW = "v" * 24


def vclient(tmp_path, view=VIEW):
    return TestClient(create_app(Frame(CFG, FakeIm(), Store(tmp_path / "s.db")), "t" * 24, view))


def bearer(t):
    return {"Authorization": "Bearer " + t}


def test_view_token_works_on_the_four_viewing_routes(tmp_path):
    c = vclient(tmp_path)
    for method, path in (("get", "/state"), ("get", "/image.jpg"), ("post", "/next"), ("post", "/previous")):
        r = getattr(c, method)(path, headers=bearer(VIEW))
        assert r.status_code in (200, 409), path  # /previous may find no history, but it must pass auth


def test_view_token_is_refused_on_control_routes(tmp_path):
    c = vclient(tmp_path)
    for path in ("/block", "/reevaluate", "/undo-block"):
        assert c.post(path, headers=bearer(VIEW)).status_code == 403
    assert c.post("/min-score", json={"value": 1}, headers=bearer(VIEW)).status_code == 403
    assert c.get("/options", headers=bearer(VIEW)).status_code == 403
    assert c.get("/state", headers=bearer("x" * 24)).status_code == 401


def test_full_token_still_works_with_view_token_set(tmp_path):
    assert vclient(tmp_path).get("/state", headers=H).status_code == 200


def test_show_is_404_when_slideshow_is_off(tmp_path):
    c, _ = client(tmp_path)
    for path in ("/show?key=x", "/show.js", "/show.css"):
        assert c.get(path).status_code == 404


def test_show_with_a_wrong_key_is_401(tmp_path):
    c = vclient(tmp_path)
    for path in ("/show?key=wrong", "/show"):
        r = c.get(path)
        assert r.status_code == 401 and "text/html" in r.headers["content-type"]
        assert "Key not accepted" in r.text
        assert r.headers["referrer-policy"] == "no-referrer" and "blob:" in r.headers["content-security-policy"]
        assert r.headers["cache-control"] == "no-store"


def test_show_serves_the_page_with_strict_headers(tmp_path):
    c = vclient(tmp_path)
    r = c.get(f"/show?device=kitchen&key={VIEW}")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert r.headers["referrer-policy"] == "no-referrer" and "blob:" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert c.get("/show?key=" + "t" * 24).status_code == 401  # the control token never belongs in a kiosk URL
    assert c.get(f"/show?device=BAD!&key={VIEW}").status_code == 422
    assert c.get("/show.js").status_code == 200 and c.get("/show.css").status_code == 200


@pytest.mark.parametrize("view", ["short", "t" * 24])
def test_build_refuses_a_short_or_reused_view_token(view, monkeypatch):
    monkeypatch.setattr(app_mod, "load_config", lambda: CFG)
    monkeypatch.setenv("FRAME_TOKEN", "t" * 24)
    monkeypatch.setenv("SLIDESHOW_TOKEN", view)
    with pytest.raises(SystemExit):
        app_mod.build()


def test_access_log_filter_hides_the_key():
    import logging

    rec = logging.LogRecord("uvicorn.access", 20, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", "/show?device=k&key=SECRET&x=1", "1.1", 200), None)
    app_mod.RedactKey().filter(rec)
    assert "SECRET" not in rec.getMessage() and "device=k" in rec.getMessage() and "x=1" in rec.getMessage()
