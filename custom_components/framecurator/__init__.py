"""Frame Curator: a curated Immich photo frame."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, FrameApi
from .const import CONF_DEVICE, CONF_HEIGHT, CONF_WIDTH, DEFAULT_SIZE

PLATFORMS = [Platform.IMAGE, Platform.BUTTON, Platform.SELECT, Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]
EVENT_PHOTO_CHANGED = "framecurator_photo_changed"
_LOGGER = logging.getLogger(__name__)

type FrameConfigEntry = ConfigEntry[FrameCoordinator]


class FrameCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, entry: FrameConfigEntry, api: FrameApi) -> None:
        # the server owns rotation; polling only notices when the photo changed
        super().__init__(hass, _LOGGER, name="Frame Curator", config_entry=entry, update_interval=timedelta(seconds=30))
        self.api = api
        self._last_changed: str | None = None
        self.options: dict = {}  # people, albums and places the selects offer

    def _announce(self, data: dict) -> None:
        """Fire an event when the displayed photo changed, but not for the first value after startup."""
        changed = data.get("changed_at")
        if self._last_changed is not None and changed != self._last_changed:
            payload = {k: v for k, v in data.items() if k not in ("asset_id", "changed_at")}
            self.hass.bus.async_fire(EVENT_PHOTO_CHANGED, {**payload, "device": self.config_entry.data[CONF_DEVICE]})
        self._last_changed = changed

    @callback
    def async_set_updated_data(self, data: dict) -> None:
        # buttons and the mode select push the API's reply here instead of waiting for the next poll
        self._announce(data)
        super().async_set_updated_data(data)

    async def _async_update_data(self) -> dict:
        try:
            data = await self.api.state()
            self.options = await self.api.options()
            self._announce(data)
            return data
        except AuthError as err:
            raise ConfigEntryAuthFailed from err
        except Exception as err:
            raise UpdateFailed(f"Frame Curator unreachable: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: FrameConfigEntry) -> bool:
    api = FrameApi(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_TOKEN], entry.data[CONF_DEVICE],
                   (entry.data[CONF_WIDTH], entry.data[CONF_HEIGHT]))
    entry.runtime_data = FrameCoordinator(hass, entry, api)
    await entry.runtime_data.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FrameConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: FrameConfigEntry) -> bool:
    """Version 1 had one global frame: it becomes the "default" device on a 1920x1200 panel."""
    if entry.version == 1:
        data = {**entry.data, CONF_DEVICE: "default", CONF_WIDTH: DEFAULT_SIZE[0], CONF_HEIGHT: DEFAULT_SIZE[1]}
        hass.config_entries.async_update_entry(entry, data=data, unique_id=f"{entry.data[CONF_URL]}|default", version=2)
    return True
