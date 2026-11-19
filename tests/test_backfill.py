import json
from pathlib import Path

import pytest

from framecurator import backfill
from framecurator.store import Store


class FakeIm:
    def __init__(self, pages, blocked=()):
        self.pages, self.blocked, self.tagged = pages, set(blocked), []

    def old_assets(self):
        yield from self.pages

    def tag_id(self, value, create=False):
        return value

    def tagged_ids(self, tag):
        return set(self.blocked) if tag == "frame/block" else set()

    def tag_assets(self, tag, ids):
        assert tag == "frame/yes"  # the backfill never writes frame/no
        self.tagged += ids


def asset(i):
    return {"id": i, "localDateTime": "2020-05-01T10:00:00.000Z", "fileCreatedAt": "2020-05-01T10:00:00.000Z"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    judged = []

    def classify_one(cfg, im, home, store, ctx, a):
        judged.append(a["id"])
        if a["id"].startswith("boom"):
            raise RuntimeError("ollama is down")
        return {"asset": a, "verdict": "kept" if a["id"].startswith("k") else "dropped", "reason": "vlm: x 7", "at_home": False}

    state = {"im": None}
    monkeypatch.setattr(backfill, "load_config", lambda: {"data_dir": "data"})
    monkeypatch.setattr(backfill, "Immich", lambda cfg: state["im"])
    monkeypatch.setattr(backfill, "home_coords", lambda cfg: (0, 0))
    monkeypatch.setattr(backfill, "context", lambda cfg, im: ((), (), {}))
    monkeypatch.setattr(backfill, "classify_one", classify_one)
    monkeypatch.setattr(backfill, "ROOT", tmp_path)
    monkeypatch.setattr(backfill, "render", lambda rows, im: f"<html>{len(rows)}</html>")
    return state, judged, Store(tmp_path / "data" / "state.db")


def run(**kw):
    return backfill.run(**{"hours": 5, "limit": 0, "sample": 0, "log": lambda m: None, **kw})


def test_keepers_are_tagged_rejects_are_only_recorded_and_a_rerun_does_nothing(env):
    state, judged, store = env
    state["im"] = FakeIm([[asset("k1"), asset("d1")], [asset("k2"), asset("d2")]])
    assert run() == 0
    assert sorted(state["im"].tagged) == ["k1", "k2"]  # frame/yes only
    rows = {a: (v, p) for a, v, p in store.db.execute("SELECT asset_id, verdict, policy FROM applied")}
    assert rows == {"k1": ("frame/yes", "yes_only"), "k2": ("frame/yes", "yes_only"), "d1": ("frame/no", "yes_only"), "d2": ("frame/no", "yes_only")}
    judged.clear()
    state["im"].tagged.clear()
    assert run() == 0 and judged == [] and state["im"].tagged == []  # nothing is judged or tagged twice
    assert json.loads(store.get("backfill"))["judged"] == 4


def test_limit_stops_and_the_next_run_continues(env):
    state, judged, store = env
    state["im"] = FakeIm([[asset("k1"), asset("d1"), asset("k2")], [asset("d2"), asset("k3")]])
    run(limit=2)
    assert judged == ["k1", "d1"] and json.loads(store.get("backfill"))["finished"] is False
    run(limit=0)
    assert judged == ["k1", "d1", "k2", "d2", "k3"]  # continued, with no repeats
    assert sorted(state["im"].tagged) == ["k1", "k2", "k3"] and json.loads(store.get("backfill"))["finished"] is True


def test_time_budget_stops_the_run(env):
    state, judged, store = env
    state["im"] = FakeIm([[asset(f"d{i}") for i in range(50)]])
    clock = iter(range(1000))  # each look at the clock is one second
    run(hours=10 / 3600, now=lambda: next(clock))
    assert 0 < len(judged) < 50 and json.loads(store.get("backfill"))["finished"] is False


def test_repeated_failures_end_the_run_without_recording_anything(env):
    state, judged, store = env
    state["im"] = FakeIm([[asset("boom1"), asset("boom2"), asset("boom3"), asset("k1")]])
    assert run() == 2  # a distinct exit code for "gave up"
    assert judged == ["boom1", "boom2", "boom3"] and store.applied_ids() == set()  # k1 was never reached, nothing was marked done


def test_a_single_failure_is_skipped_and_retried_next_time(env):
    state, _judged, store = env
    state["im"] = FakeIm([[asset("boom1"), asset("k1"), asset("d1")]])
    assert run() == 0
    assert store.applied_ids() == {"k1", "d1"}  # boom1 stays unrecorded, so a later run retries it


def test_applied_and_blocked_photos_are_skipped(env):
    state, judged, store = env
    store.put_applied("k1", "frame/yes", "r")
    state["im"] = FakeIm([[asset("k1"), asset("k2"), asset("k3")]], blocked=["k3"])
    run()
    assert judged == ["k2"]


def test_sample_changes_nothing_and_writes_a_report(env, tmp_path):
    state, judged, store = env
    state["im"] = FakeIm([[asset(f"k{i}") for i in range(30)], [asset(f"d{i}") for i in range(30)]])
    assert run(sample=10) == 0
    assert len(judged) == 10 and state["im"].tagged == [] and store.applied_ids() == set()
    assert store.get("backfill") is None
    assert (Path(tmp_path) / "reports" / "backfill-sample.html").read_text() == "<html>10</html>"
    assert {j[0] for j in judged} == {"k", "d"}  # drawn from across the library, not just the first page


def _status_error(code):
    import httpx

    return httpx.HTTPStatusError("x", request=httpx.Request("GET", "http://x"), response=httpx.Response(code))


def test_a_photo_without_a_preview_is_recorded_as_unjudgeable_not_a_failure(tmp_path):
    from framecurator import dryrun

    class Im:
        def thumb(self, aid, size):
            raise _status_error(404)

    row = dryrun.classify_one({"home": {"radius_m": 300}, "screenshot_name": "x", "travel_km": 30, "ollama": {"min_score": 6, "model": "m"}},
                              Im(), (0, 0), Store(tmp_path / "s.db"), ((), (), {}), {"id": "a", "exifInfo": {"make": "X"}, "visibility": "timeline",
                                                                    "originalFileName": "a.jpg"})
    assert row["verdict"] == "dropped" and row["reason"] == "no preview image in Immich"


def test_an_ollama_404_is_a_failure_not_a_no_preview_reject(monkeypatch, tmp_path):
    from framecurator import dryrun

    class Im:
        def thumb(self, aid, size):
            return b"jpg"

    def judge(cfg, img):
        raise _status_error(404)  # model not pulled or wrong URL

    monkeypatch.setattr(dryrun, "judge", judge)
    with pytest.raises(Exception, match="x"):
        dryrun.classify_one({"home": {"radius_m": 300}, "screenshot_name": "x", "travel_km": 30,
                             "ollama": {"min_score": 6, "model": "m"}},
                            Im(), (0, 0), Store(tmp_path / "s.db"), ((), (), {}), {"id": "a", "exifInfo": {"make": "X"},
                                                                          "visibility": "timeline", "originalFileName": "a.jpg"})


def test_other_http_errors_still_propagate_so_the_run_can_stop(monkeypatch):
    from framecurator import dryrun

    def vision(cfg, im, store, aid):
        raise _status_error(500)

    monkeypatch.setattr(dryrun, "vision", vision)
    with pytest.raises(Exception, match="x"):
        dryrun.classify_one({"home": {"radius_m": 300}, "screenshot_name": "x", "travel_km": 30, "ollama": {"min_score": 6}},
                            None, (0, 0), None, ((), (), {}), {"id": "a", "exifInfo": {"make": "X"}, "visibility": "timeline",
                                                                  "originalFileName": "a.jpg"})


def test_report_survives_a_missing_thumbnail():
    from framecurator import dryrun

    class Im:
        def thumb(self, aid):
            raise _status_error(404)

    row = {"asset": {"id": "a", "fileCreatedAt": "2020-01-01T00:00:00Z"}, "verdict": "kept", "reason": "r", "at_home": False}
    assert "data:image/jpeg;base64," in dryrun.render([row], Im())
