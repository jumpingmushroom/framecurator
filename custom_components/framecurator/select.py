from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FrameConfigEntry, FrameCoordinator
from .const import MODES
from .entity import FrameEntity


async def async_setup_entry(hass: HomeAssistant, entry: FrameConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    async_add_entities([FrameMode(c), *(FrameFilter(c, kind) for kind in ("person", "album", "place"))])


class FrameMode(FrameEntity, SelectEntity):
    _attr_name = "Mode"
    _attr_icon = "mdi:image-multiple"
    _attr_options = MODES

    def __init__(self, coordinator: FrameCoordinator) -> None:
        super().__init__(coordinator, "mode")

    @property
    def current_option(self) -> str | None:
        return (self.coordinator.data or {}).get("mode")

    async def async_select_option(self, option: str) -> None:
        await self._push(self.coordinator.api.set_mode(option))


OPTION_KEY = {"person": "people", "album": "albums", "place": "places"}  # where the API lists each kind


class FrameFilter(FrameEntity, SelectEntity):
    """Choose a person, album or place; choosing one also switches the display to that mode."""

    def __init__(self, coordinator: FrameCoordinator, kind: str) -> None:
        super().__init__(coordinator, kind)
        self._kind = kind
        self._attr_name = kind.capitalize()
        self._attr_icon = {"person": "mdi:account", "album": "mdi:image-album", "place": "mdi:map-marker"}[kind]

    @property
    def options(self) -> list[str]:
        return self.coordinator.options.get(OPTION_KEY[self._kind], [])

    @property
    def current_option(self) -> str | None:
        value = (self.coordinator.data or {}).get("place_filter" if self._kind == "place" else self._kind)
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self._push(self.coordinator.api.set_filter(self._kind, option))
