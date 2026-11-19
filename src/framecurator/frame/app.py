"""Frame API: serves the current photo (rendered for the panel) and its caption data. LAN only, bearer token."""
import hmac
import json
import logging
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from ..immich import ROOT, Immich, load_config
from ..store import Store
from ..vlm import JUNK
from .render import render
from .select import MODES, pick, taken

BLOCK = "frame/block"
MAX_DEVICES = 16  # each device keeps its own state, so cap what a token holder can create
DEVICE = Query("default", pattern=r"^[a-z0-9_-]{1,32}$")
WIDTH = Query(None, ge=320, le=4096)
HEIGHT = Query(None, ge=320, le=4096)
RENDER_CACHE = 8
HISTORY = 20  # photos Previous can step back through
FILTERS = ("person", "album", "place")  # modes that also need a chosen value
ALL_MODES = {*MODES, "favorites", *FILTERS}
YES, NO = "frame/yes", "frame/no"
STATIC = Path(__file__).parent / "static"


def place_of(asset):
    exif = asset.get("exifInfo") or {}
    return ", ".join(x for x in (exif.get("city"), exif.get("country")) if x) or None


def names_of(asset):
    return [p["name"] for p in asset.get("people") or [] if p.get("name")]


class RedactKey(logging.Filter):
    """Keep the slideshow key out of uvicorn's access log, which records the full request path."""

    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(re.sub(r"([?&]key=)[^&\s]*", r"\1***", a) if isinstance(a, str) else a for a in record.args)
        return True


class Frame:
    def __init__(self, cfg, im, store):
        self.cfg, self.im, self.store = cfg, im, store
        self.lock = threading.Lock()
        self.pool, self.picks, self.pool_at, self.album_names = {}, set(), 0.0, []
        self.rendered = {}  # (asset id, width, height) -> jpeg, oldest first

    def refresh(self):
        if time.time() - self.pool_at < self.cfg["frame"]["pool_ttl_minutes"] * 60 and self.pool:
            return
        im = self.im
        picks = im.album_assets(self.cfg["picks_album"])
        blocked = im.tagged_ids(im.tag_id(BLOCK))
        assets = {a["id"]: a for a in im.tagged_assets(im.tag_id("frame/yes")) + picks if a["id"] not in blocked}
        self.pool, self.picks, self.pool_at = assets, {a["id"] for a in picks}, time.time()
        self.album_names = im.album_names()

    def _state(self, device):
        raw = self.store.get(f"current:{device}")
        if raw:
            return json.loads(raw)
        if len(self.store.devices()) >= MAX_DEVICES:
            raise HTTPException(422, "too many devices")
        return {"asset_id": None, "since": 0, "mode": "mixed", "bucket": None}

    def _save(self, state, device):
        self.store.put(f"current:{device}", json.dumps(state))

    def _show(self, state, device, asset_id, bucket):
        """Make asset_id the displayed photo; the one it replaces goes onto the back stack for Previous."""
        if state["asset_id"] and state["asset_id"] != asset_id:
            state["history"] = (state.get("history", []) + [state["asset_id"]])[-HISTORY:]
        state.update(asset_id=asset_id, since=time.time(), bucket=bucket)
        self._save(state, device)
        return state

    def _mix(self, state):
        """The display's mix weights as percentages; config.yaml writes them as fractions."""
        return state.get("mix") or {k: round(v * 100) for k, v in self.cfg["mix"].items()}

    def _candidates(self, state):
        """Pool photos matching the device's filter mode, or None when the mode has no filter."""
        mode, pool = state["mode"], list(self.pool.values())
        if mode == "favorites":
            return [a for a in pool if a.get("isFavorite")]
        if mode == "person":
            return [a for a in pool if state.get("person") in names_of(a)]
        if mode == "place":
            return [a for a in pool if state.get("place") in (place_of(a), (a.get("exifInfo") or {}).get("country"))]
        if mode == "album":
            ids = {a["id"] for a in self.im.album_assets(state["album"])}
            return [a for a in pool if a["id"] in ids]
        return None

    def _advance(self, state, device):
        candidates = self._candidates(state)
        # a filter that matches nothing (any more) falls back to the whole pool instead of showing nothing
        assets, mode = (candidates, "mixed") if candidates else (list(self.pool.values()), state["mode"] if candidates is None else "mixed")
        chosen = pick(assets, self.store.shown_since(state.get("repeat_days", self.cfg["repeat_days"]), device), self.picks,
                      self._mix(state), mode, datetime.now())
        if chosen is None:
            raise HTTPException(503, "no curated photos yet")
        asset, bucket = chosen
        self.store.put_shown(asset["id"], device)
        return self._show(state, device, asset["id"], bucket)

    def _interval(self, state):
        return state.get("interval") or self.cfg["frame"]["rotate_minutes"]

    def current(self, device="default", force_next=False):
        """Current state of a device, rotating when due (unless paused) or when its photo left the pool."""
        with self.lock:
            self.refresh()
            state = self._state(device)
            due = not state.get("paused") and time.time() - state["since"] > self._interval(state) * 60
            if force_next or due or state["asset_id"] not in self.pool:
                state = self._advance(state, device)
            return state

    def _edit(self, device, **changes):
        with self.lock:
            state = self._state(device)
            state.update(changes)
            self._save(state, device)

    def _check_matches(self, state):
        candidates = self._candidates(state)  # None for modes without a filter
        if candidates is not None and not candidates:
            raise HTTPException(409, "no curated photos match that")

    def set_mode(self, mode, device="default"):
        with self.lock:
            self.refresh()
            state = self._state(device)
            if mode in FILTERS and not state.get(mode):
                raise HTTPException(409, f"choose a {mode} first")
            state["mode"] = mode
            self._check_matches(state)
            self._save(state, device)
        return self.current(device, force_next=True)

    def set_filter(self, kind, value, device="default"):
        """Choose a person, album or place; this also switches the display to that mode."""
        with self.lock:
            self.refresh()
            state = self._state(device)
            state.update({kind: value, "mode": kind})
            self._check_matches(state)
            self._save(state, device)
        return self.current(device, force_next=True)

    def options(self):
        with self.lock:
            self.refresh()
            people, places = {}, set()
            for a in self.pool.values():
                for n in names_of(a):
                    people[n] = people.get(n, 0) + 1
                exif = a.get("exifInfo") or {}
                places |= {x for x in (exif.get("country"), place_of(a)) if x}
            return {"people": sorted(people, key=lambda n: (-people[n], n)), "albums": list(self.album_names),
                    "places": sorted(places, key=lambda p: (", " in p, p))}  # countries first, then cities

    def set_settings(self, mix, repeat_days, device="default"):
        self.current(device)
        with self.lock:
            state = self._state(device)
            if mix:
                state["mix"] = {**self._mix(state), **mix}
            if repeat_days is not None:
                state["repeat_days"] = repeat_days
            self._save(state, device)
        return self.current(device)

    def min_score(self):
        return int(self.store.get("min_score") or self.cfg["ollama"]["min_score"])

    def reevaluate(self):
        """Re-apply the minimum vision score to photos the curator decided on score alone.

        Needs no Ollama: scores are stored. Photos whose tag was changed by hand, and blocked ones, are left alone.
        Backfilled photos ('yes_only') have no frame/no tag, so a reject is expected to carry no tag at all."""
        im, min_score = self.im, self.min_score()
        ids = {t: im.tag_id(t, create=True) for t in (YES, NO, BLOCK)}
        tagged = {t: im.tagged_ids(i) for t, i in ids.items()}
        moves = {YES: [], NO: []}  # want -> [(asset_id, reason, yes_only)]
        edited = 0
        for asset_id, verdict, reason, policy in self.store.db.execute("SELECT asset_id, verdict, reason, policy FROM applied").fetchall():
            m = re.fullmatch(r"vlm: (\w+) (\d+)", reason)
            if not m:
                continue  # decided by a rule, not by the score
            yes_only = policy == "yes_only"
            expected = None if (yes_only and verdict == NO) else verdict
            current = YES if asset_id in tagged[YES] else NO if asset_id in tagged[NO] else None
            if current != expected or asset_id in tagged[BLOCK]:
                edited += 1
                continue
            want = YES if m.group(1) not in JUNK and int(m.group(2)) >= min_score else NO
            if want != verdict:
                moves[want].append((asset_id, reason, yes_only))
        expect = []
        for want, rows in moves.items():
            if not rows:
                continue
            everyone = [r[0] for r in rows]
            tagged_no = [r[0] for r in rows if not r[2]]  # only photos that carry frame/no tags move between the two tags
            if want == YES:
                im.untag_assets(ids[NO], tagged_no)
                im.tag_assets(ids[YES], everyone)
                expect += [(ids[YES], everyone, True), (ids[NO], tagged_no, False)]
            else:
                im.untag_assets(ids[YES], everyone)
                im.tag_assets(ids[NO], tagged_no)  # a backfilled keeper that is demoted just loses its tag
                expect += [(ids[NO], tagged_no, True), (ids[YES], everyone, False)]
            for asset_id, reason, yes_only in rows:
                self.store.put_applied(asset_id, want, reason, policy="yes_only" if yes_only else "both")
        self.pool_at = 0
        settled = im.settle([e for e in expect if e[1]]) if expect else True  # see Immich.settle
        return {"min_score": min_score, "moved_to_yes": len(moves[YES]), "moved_to_no": len(moves[NO]), "left_alone": edited,
                "settled": settled}

    def set_paused(self, paused, device="default"):
        self.current(device)  # make sure the device has a photo before pausing it
        self._edit(device, paused=paused, since=time.time())  # resuming restarts the countdown
        return self.current(device)

    def set_interval(self, minutes, device="default"):
        self.current(device)
        self._edit(device, interval=minutes, since=time.time())
        return self.current(device)

    def previous(self, device="default"):
        state = self.current(device)
        with self.lock:
            history = state.get("history", [])
            while history and history[-1] not in self.pool:  # blocked or removed since: skip it
                history.pop()
            if not history:
                raise HTTPException(409, "no earlier photo")
            state["history"], back = history[:-1], history[-1]
            state.update(asset_id=back, since=time.time(), bucket="previous")  # not pushed on the back stack again
            self._save(state, device)
            return state

    def block(self, device="default"):
        state = self.current(device)
        self.im.tag_assets(self.im.tag_id(BLOCK, create=True), [state["asset_id"]])
        self.store.put_blocked(state["asset_id"], device)
        self.pool_at = 0  # drop the blocked photo from the pool immediately; other devices showing it move on too
        return self.current(device, force_next=True)

    def undo_block(self, device="default"):
        self.current(device)
        asset_id = self.store.pop_blocked(device)
        if asset_id is None:
            raise HTTPException(409, "nothing to undo")
        self.im.untag_assets(self.im.tag_id(BLOCK), [asset_id])
        with self.lock:
            self.pool_at = 0
            self.refresh()
            state = self._state(device)
            if asset_id in self.pool:  # bring the photo back on screen
                state = self._show(state, device, asset_id, "previous")
        return self.current(device)

    def set_favorite(self, on, device="default"):
        state = self.current(device)
        self.im.set_favorite(state["asset_id"], on)
        self.pool[state["asset_id"]]["isFavorite"] = on  # keep the cached copy in step until the next refresh
        return state

    def set_pick(self, on, device="default"):
        state = self.current(device)
        album = self.im.album_id(self.cfg["picks_album"])
        if album is None:
            raise HTTPException(409, f"album {self.cfg['picks_album']!r} does not exist in Immich")
        (self.im.album_add if on else self.im.album_remove)(album, [state["asset_id"]])
        (self.picks.add if on else self.picks.discard)(state["asset_id"])
        if not on:
            self.pool_at = 0  # a photo that was in the pool only as a pick leaves it
        return self.current(device)

    def feedback(self, value, device="default"):
        state = self.current(device)
        self.store.put_taste(state["asset_id"], device, value)  # kept for threshold tuning later; nothing reads it yet
        return state

    def meta(self, state, device="default"):
        a = self.pool[state["asset_id"]]
        exif = a.get("exifInfo") or {}
        t = taken(a)
        place = ", ".join(x for x in (exif.get("city"), exif.get("country")) if x) or None  # never ""
        years_ago = datetime.now().year - t.year
        # memories read "3 years ago"; everything else shows the date. English month names: a card can format captured_at itself.
        when = f"{years_ago} year{'s' * (years_ago != 1)} ago" if state["bucket"] == "on_this_day" and years_ago else f"{t:%-d %b %Y}"
        paused, interval = bool(state.get("paused")), self._interval(state)
        return {"changed_at": datetime.fromtimestamp(state["since"], UTC).isoformat(), "asset_id": a["id"],
                "next_change_at": None if paused else datetime.fromtimestamp(state["since"] + interval * 60, UTC).isoformat(),
                "paused": paused, "interval_minutes": interval, "person": state.get("person"), "album": state.get("album"),
                "place_filter": state.get("place"), "mix": self._mix(state),
                "repeat_days": state.get("repeat_days", self.cfg["repeat_days"]), "min_score": self.min_score(), "is_favorite": bool(a.get("isFavorite")),
                "is_pick": a["id"] in self.picks, "can_go_back": bool(state.get("history")),
                "can_undo": self.store.has_blocked(device),
                "mode": state["mode"], "bucket": state["bucket"], "date": t.date().isoformat(),
                "captured_at": (t if t.tzinfo else t.replace(tzinfo=UTC)).isoformat(),
                "years_ago": years_ago, "place": place, "location": place, "caption": " · ".join(x for x in (place, when) if x),
                "people": [p["name"] for p in a.get("people") or [] if p.get("name")]}

    def image(self, state, width=None, height=None):
        d = self.cfg["display"]
        key = (state["asset_id"], width or d["width"], height or d["height"])
        if key not in self.rendered:
            jpeg = self.im.thumb(key[0], self.cfg["frame"]["image_size"])
            self.rendered[key] = render(jpeg, self.im.faces(key[0]), key[1], key[2])
            while len(self.rendered) > RENDER_CACHE:
                self.rendered.pop(next(iter(self.rendered)))
        return self.rendered[key]


class ModeBody(BaseModel):
    mode: str


class FilterBody(BaseModel):
    kind: str
    value: str = Field(min_length=1, max_length=200)


class SettingsBody(BaseModel):
    mix: dict[str, float] | None = None
    repeat_days: int | None = Field(default=None, ge=0, le=365)


class ScoreBody(BaseModel):
    value: int = Field(ge=1, le=10)


class OnBody(BaseModel):
    on: bool


class MinutesBody(BaseModel):
    minutes: int = Field(ge=1, le=1440)


class ValueBody(BaseModel):
    value: int = Field(ge=-1, le=1)


def create_app(frame, token, view_token=None):
    bearer = HTTPBearer(auto_error=False)

    def same(given, secret):
        return bool(secret) and hmac.compare_digest(given.encode(), secret.encode())

    def auth(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if cred is not None and view_token and same(cred.credentials, view_token) and not same(cred.credentials, token):
            raise HTTPException(403, "this token can only view")  # the slideshow token sits in a URL: view and skip only
        if cred is None or not same(cred.credentials, token):
            raise HTTPException(401, "unauthorized")

    def viewer(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if cred is None or not (same(cred.credentials, token) or same(cred.credentials, view_token or "")):
            raise HTTPException(401, "unauthorized")

    app = FastAPI(title="framecurator", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/state", dependencies=[Depends(viewer)])
    def state(device: str = DEVICE):
        return frame.meta(frame.current(device), device)

    @app.get("/image.jpg", dependencies=[Depends(viewer)])
    def image(device: str = DEVICE, w: int | None = WIDTH, h: int | None = HEIGHT):
        return Response(frame.image(frame.current(device), w, h), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/next", dependencies=[Depends(viewer)])
    def next_(device: str = DEVICE):
        return frame.meta(frame.current(device, force_next=True), device)

    @app.post("/block", dependencies=[Depends(auth)])
    def block(device: str = DEVICE):
        return frame.meta(frame.block(device), device)

    @app.post("/mode", dependencies=[Depends(auth)])
    def mode(body: ModeBody, device: str = DEVICE):
        if body.mode not in ALL_MODES:
            raise HTTPException(422, f"mode must be one of {sorted(ALL_MODES)}")
        return frame.meta(frame.set_mode(body.mode, device), device)

    @app.get("/options", dependencies=[Depends(auth)])
    def options():
        return frame.options()

    @app.post("/filter", dependencies=[Depends(auth)])
    def filter_(body: FilterBody, device: str = DEVICE):
        if body.kind not in FILTERS:
            raise HTTPException(422, f"kind must be one of {list(FILTERS)}")
        return frame.meta(frame.set_filter(body.kind, body.value, device), device)

    @app.post("/settings", dependencies=[Depends(auth)])
    def settings(body: SettingsBody, device: str = DEVICE):
        unknown = set(body.mix or {}) - set(frame.cfg["mix"])
        if unknown or any(not 0 <= w <= 100 for w in (body.mix or {}).values()):
            raise HTTPException(422, f"mix weights must be 0-100 for {sorted(frame.cfg['mix'])}")
        return frame.meta(frame.set_settings(body.mix, body.repeat_days, device), device)

    @app.post("/min-score", dependencies=[Depends(auth)])
    def min_score(body: ScoreBody, device: str = DEVICE):
        frame.store.put("min_score", str(body.value))  # shared by all displays and read by the curator too
        return frame.meta(frame.current(device), device)

    @app.post("/reevaluate", dependencies=[Depends(auth)])
    def reevaluate():
        return frame.reevaluate()

    @app.post("/previous", dependencies=[Depends(viewer)])
    def previous(device: str = DEVICE):
        return frame.meta(frame.previous(device), device)

    @app.post("/pause", dependencies=[Depends(auth)])
    def pause(body: OnBody, device: str = DEVICE):
        return frame.meta(frame.set_paused(body.on, device), device)

    @app.post("/interval", dependencies=[Depends(auth)])
    def interval(body: MinutesBody, device: str = DEVICE):
        return frame.meta(frame.set_interval(body.minutes, device), device)

    @app.post("/undo-block", dependencies=[Depends(auth)])
    def undo_block(device: str = DEVICE):
        return frame.meta(frame.undo_block(device), device)

    @app.post("/favorite", dependencies=[Depends(auth)])
    def favorite(body: OnBody, device: str = DEVICE):
        return frame.meta(frame.set_favorite(body.on, device), device)

    @app.post("/pick", dependencies=[Depends(auth)])
    def pick_(body: OnBody, device: str = DEVICE):
        return frame.meta(frame.set_pick(body.on, device), device)

    @app.post("/feedback", dependencies=[Depends(auth)])
    def feedback(body: ValueBody, device: str = DEVICE):
        if body.value == 0:
            raise HTTPException(422, "value must be 1 (more) or -1 (less)")
        return frame.meta(frame.feedback(body.value, device), device)

    def static(name, media_type):
        if not view_token:
            raise HTTPException(404, "slideshow is off")
        return Response((STATIC / name).read_bytes(), media_type=media_type, headers={"Cache-Control": "no-store"})

    @app.get("/show")
    def show(device: str = DEVICE, key: str = ""):
        if not view_token:
            raise HTTPException(404, "slideshow is off")
        headers = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
                   "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:"}
        if not same(key, view_token):  # a kiosk shows this, so say it calmly instead of raw JSON
            page = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                    '<link rel="stylesheet" href="/show.css"><body><div id="msg">Key not accepted</div>')
            return HTMLResponse(page, status_code=401, headers=headers)
        return HTMLResponse((STATIC / "show.html").read_text(), headers=headers)

    @app.get("/show.js")
    def show_js():
        return static("show.js", "text/javascript")

    @app.get("/show.css")
    def show_css():
        return static("show.css", "text/css")

    return app


def build():
    cfg = load_config()
    token = os.environ["FRAME_TOKEN"]
    if len(token) < 24:
        raise SystemExit("FRAME_TOKEN must be at least 24 characters")
    view = os.environ.get("SLIDESHOW_TOKEN", "")  # empty = slideshow off
    if view and (len(view) < 24 or view == token):
        raise SystemExit("SLIDESHOW_TOKEN must be at least 24 characters and differ from FRAME_TOKEN")
    logging.getLogger("uvicorn.access").addFilter(RedactKey())
    im = Immich(cfg, "IMMICH_FRAME_KEY")
    im.check_version()
    frame = Frame(cfg, im, Store(ROOT / cfg["data_dir"] / "state.db"))
    return create_app(frame, token, view or None)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build(), host="0.0.0.0", port=load_config()["frame"]["port"])
