from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FrameConfigEntry, FrameCoordinator
from .entity import FrameEntity


async def async_setup_entry(hass: HomeAssistant, entry: FrameConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([FrameImage(entry.runtime_data)])


class FrameImage(FrameEntity, ImageEntity):
    _attr_name = None  # the device name is the entity name

    def __init__(self, coordinator: FrameCoordinator) -> None:
        FrameEntity.__init__(self, coordinator, "image")
        ImageEntity.__init__(self, coordinator.hass)

    @property
    def image_last_updated(self) -> datetime | None:
        return datetime.fromisoformat(self.coordinator.data["changed_at"]) if self.coordinator.data else None

    async def async_image(self) -> bytes | None:
        return await self.coordinator.api.image()

    @property
    def extra_state_attributes(self) -> dict:
        # every API field except the internal ones, so new caption fields need no integration change
        return {k: v for k, v in (self.coordinator.data or {}).items() if k not in ("asset_id", "changed_at")}
