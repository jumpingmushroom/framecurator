from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FrameConfigEntry, FrameCoordinator
from .api import FrameApi
from .entity import FrameEntity


@dataclass(frozen=True, kw_only=True)
class FrameSwitchDescription(SwitchEntityDescription):
    field: str  # key in the state dict that holds the on/off value
    call: Any  # async (FrameApi, bool) -> state dict


SWITCHES = (
    FrameSwitchDescription(key="pause", name="Pause", icon="mdi:pause-circle-outline", field="paused", call=FrameApi.pause),
    FrameSwitchDescription(key="favorite", name="Favorite", icon="mdi:heart-outline", field="is_favorite", call=FrameApi.favorite),
    FrameSwitchDescription(key="pick", name="Pick", icon="mdi:star-outline", field="is_pick", call=FrameApi.pick),
)


async def async_setup_entry(hass: HomeAssistant, entry: FrameConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(FrameSwitch(entry.runtime_data, d) for d in SWITCHES)


class FrameSwitch(FrameEntity, SwitchEntity):
    entity_description: FrameSwitchDescription

    def __init__(self, coordinator: FrameCoordinator, description: FrameSwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return bool(data.get(self.entity_description.field)) if data else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._push(self.entity_description.call(self.coordinator.api, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._push(self.entity_description.call(self.coordinator.api, False))
