from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FrameConfigEntry, FrameCoordinator
from .api import FrameApi
from .entity import FrameEntity


@dataclass(frozen=True, kw_only=True)
class FrameButtonDescription(ButtonEntityDescription):
    press: Any  # async (FrameApi) -> state dict
    available: Any = None  # optional (state dict) -> bool


BUTTONS = (
    FrameButtonDescription(key="skip", name="Skip", icon="mdi:skip-next", press=FrameApi.next),
    FrameButtonDescription(key="previous", name="Previous", icon="mdi:skip-previous", press=FrameApi.previous,
                           available=lambda d: d.get("can_go_back", False)),
    FrameButtonDescription(key="never_show", name="Never show this", icon="mdi:eye-off", press=FrameApi.block),
    FrameButtonDescription(key="undo_never_show", name="Undo never show", icon="mdi:eye-refresh", press=FrameApi.undo_block,
                           available=lambda d: d.get("can_undo", False)),
    FrameButtonDescription(key="reevaluate", name="Re-evaluate", icon="mdi:refresh-auto", entity_category=EntityCategory.CONFIG,
                           press=FrameApi.reevaluate),
    FrameButtonDescription(key="more_like_this", name="More like this", icon="mdi:thumb-up-outline",
                           press=lambda api: api.feedback(1)),
    FrameButtonDescription(key="less_like_this", name="Less like this", icon="mdi:thumb-down-outline",
                           press=lambda api: api.feedback(-1)),
)


async def async_setup_entry(hass: HomeAssistant, entry: FrameConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(FrameButton(entry.runtime_data, d) for d in BUTTONS)


class FrameButton(FrameEntity, ButtonEntity):
    entity_description: FrameButtonDescription

    def __init__(self, coordinator: FrameCoordinator, description: FrameButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        ok = self.entity_description.available
        return super().available and (ok is None or ok(self.coordinator.data or {}))

    async def async_press(self) -> None:
        result = await self.entity_description.press(self.coordinator.api)
        if self.entity_description.key == "reevaluate":  # the reply is a summary, not a display state
            self.hass.bus.async_fire("framecurator_reevaluated", result)
            await self.coordinator.async_request_refresh()
        else:
            self.coordinator.async_set_updated_data(result)
