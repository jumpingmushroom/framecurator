import httpx
import pytest

from framecurator import immich
from framecurator.immich import Immich


class Stub(Immich):
    """Immich with its HTTP calls replaced by an in-memory tag set that can undo the first write, like Immich's jobs do."""

    def __init__(self, undo_first_writes=0):
        self.tags, self.undo, self.applied = set(), undo_first_writes, 0

    def tagged_ids(self, tag_id):
        return set(self.tags)

    def tag_assets(self, tag_id, ids):
        self.applied += 1
        if self.undo:
            self.undo -= 1  # a background job writes the older state back
        else:
            self.tags |= set(ids)

    def untag_assets(self, tag_id, ids):
        self.tags -= set(ids)


def test_settle_reapplies_a_change_that_was_written_back(monkeypatch):
    monkeypatch.setattr(immich.time, "sleep", lambda s: None)
    im = Stub(undo_first_writes=1)
    im.tag_assets("t", ["a"])  # the original change, undone by Immich
    assert im.tags == set()
    assert im.settle([("t", ["a"], True)]) is True and im.tags == {"a"}


def test_settle_gives_up_after_the_rounds_and_says_so(monkeypatch):
    monkeypatch.setattr(immich.time, "sleep", lambda s: None)
    im = Stub(undo_first_writes=99)
    assert im.settle([("t", ["a"], True)], rounds=3) is False and im.applied == 3


def test_settle_removes_tags_that_came_back_and_does_nothing_when_all_is_well(monkeypatch):
    monkeypatch.setattr(immich.time, "sleep", lambda s: None)
    im = Stub()
    im.tags = {"a"}  # should be absent
    assert im.settle([("t", ["a"], False)]) is True and im.tags == set()
    assert im.settle([("t", ["a"], False)]) is True and im.applied == 0  # already fine: no writes


class AlbumStub(Immich):
    """Immich whose album lookup and search return canned pages."""

    def __init__(self, album, pages):
        self.album, self.pages, self.bodies = album, pages, []

    def album_id(self, name):
        return self.album

    def _search(self, kind, body):
        self.bodies.append(body)
        return self.pages[body["page"] - 1]


def test_album_ids_pages_through_the_search_not_the_album_endpoint():
    im = AlbumStub("al-1", [{"items": [{"id": "a"}, {"id": "b"}], "nextPage": "2"}, {"items": [{"id": "c"}], "nextPage": None}])
    assert im.album_ids("Holiday") == {"a", "b", "c"}
    assert [b["albumIds"] for b in im.bodies] == [["al-1"], ["al-1"]] and [b["page"] for b in im.bodies] == [1, 2]


def test_album_ids_of_a_missing_album_is_empty_and_searches_nothing():
    im = AlbumStub(None, [])
    assert im.album_ids("Nope") == set() and im.bodies == []


def _versioned(handler):
    import httpx
    im = Stub()
    im.c = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x/api")
    return im


def test_check_version_tested_is_silent():
    import httpx
    im = _versioned(lambda r: httpx.Response(200, json={"major": 3, "minor": 1, "patch": 0, "prerelease": None}))
    logs = []
    assert im.check_version(logs.append) == "v3.1.0" and logs == []


def test_check_version_warns_on_untested():
    import httpx
    im = _versioned(lambda r: httpx.Response(200, json={"major": 3, "minor": 2, "patch": 0}))
    logs = []
    assert im.check_version(logs.append) == "v3.2.0"
    assert "v3.2.0" in logs[0] and "v3.1.0" in logs[0]


def test_check_version_prerelease_is_untested():
    import httpx
    im = _versioned(lambda r: httpx.Response(200, json={"major": 3, "minor": 1, "patch": 0, "prerelease": "rc.1"}))
    logs = []
    assert im.check_version(logs.append) == "v3.1.0-rc.1" and len(logs) == 1


def test_check_version_error_returns_none():
    import httpx
    im = _versioned(lambda r: httpx.Response(500))
    logs = []
    assert im.check_version(logs.append) is None and "could not read" in logs[0]


@pytest.mark.parametrize("call", [lambda im: im.album_assets("P"), lambda im: im.album_names(),
                                  lambda im: im.album_id("P"), lambda im: im.tag_id("frame/yes")])
def test_a_rejected_key_raises_a_clear_http_error(call):
    im = Immich.__new__(Immich)
    im.c = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(401, json={"message": "Invalid API key"})),
                        base_url="http://x/api")
    with pytest.raises(httpx.HTTPStatusError, match="401"):
        call(im)
