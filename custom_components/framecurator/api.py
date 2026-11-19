"""Thin client for the Frame Curator API."""
from aiohttp import ClientSession
from homeassistant.exceptions import HomeAssistantError


class AuthError(Exception):
    """The API rejected the token."""


class FrameApi:
    def __init__(self, session: ClientSession, url: str, token: str, device: str = "default", size: tuple[int, int] | None = None):
        self._s, self._url, self._h = session, url.rstrip("/"), {"Authorization": f"Bearer {token}"}
        self._device, self._size = device, size

    async def _req(self, method, path, **kw):
        params = {"device": self._device}
        if self._size and path.endswith(".jpg"):
            params |= {"w": self._size[0], "h": self._size[1]}
        async with self._s.request(method, self._url + path, headers=self._h, params=params, timeout=30, **kw) as r:
            if r.status == 401:
                raise AuthError
            if r.status == 409:
                raise HomeAssistantError((await r.json()).get("detail", "not possible right now"))
            r.raise_for_status()
            return await (r.read() if path.endswith(".jpg") else r.json())

    async def state(self):
        return await self._req("GET", "/state")

    async def image(self):
        return await self._req("GET", "/image.jpg")

    async def next(self):
        return await self._req("POST", "/next")

    async def block(self):
        return await self._req("POST", "/block")

    async def set_mode(self, mode):
        return await self._req("POST", "/mode", json={"mode": mode})

    async def previous(self):
        return await self._req("POST", "/previous")

    async def pause(self, on):
        return await self._req("POST", "/pause", json={"on": on})

    async def interval(self, minutes):
        return await self._req("POST", "/interval", json={"minutes": minutes})

    async def undo_block(self):
        return await self._req("POST", "/undo-block")

    async def favorite(self, on):
        return await self._req("POST", "/favorite", json={"on": on})

    async def pick(self, on):
        return await self._req("POST", "/pick", json={"on": on})

    async def feedback(self, value):
        return await self._req("POST", "/feedback", json={"value": value})

    async def options(self):
        return await self._req("GET", "/options")

    async def set_filter(self, kind, value):
        return await self._req("POST", "/filter", json={"kind": kind, "value": value})

    async def settings(self, mix=None, repeat_days=None):
        return await self._req("POST", "/settings", json={"mix": mix, "repeat_days": repeat_days})

    async def min_score(self, value):
        return await self._req("POST", "/min-score", json={"value": value})

    async def reevaluate(self):
        return await self._req("POST", "/reevaluate")
