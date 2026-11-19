from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FrameConfigEntry, FrameCoordinator
from .api import FrameApi
from .entity import FrameEntity


async def async_setup_entry(hass: HomeAssistant, entry: FrameConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    async_add_entities([FrameInterval(c), *(FrameNumber(c, d) for d in NUMBERS)])


class FrameInterval(FrameEntity, NumberEntity):
    _attr_name = "Rotation interval"
    _attr_icon = "mdi:timer-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = 1, 1440, 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: FrameCoordinator) -> None:
        super().__init__(coordinator, "interval")

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("interval_minutes")

    async def async_set_native_value(self, value: float) -> None:
        await self._push(self.coordinator.api.interval(int(value)))


@dataclass(frozen=True, kw_only=True)
class FrameNumberDescription(NumberEntityDescription):
    value: Callable[[dict], Any]
    call: Callable[[FrameApi, int], Any]  # async (api, new value) -> state dict


def _mix(key: str, name: str) -> FrameNumberDescription:
    return FrameNumberDescription(key=f"mix_{key}", name=f"Mix: {name}", icon="mdi:chart-pie", native_min_value=0, native_max_value=100,
                                  native_step=5, mode=NumberMode.BOX, entity_category=EntityCategory.CONFIG,
                                  value=lambda d: d.get("mix", {}).get(key),
                                  call=lambda api, v: api.settings(mix={key: v}))


NUMBERS = (
    _mix("on_this_day", "on this day"), _mix("favorites_picks", "favorites and picks"),
    _mix("recent_30d", "recent"), _mix("library", "whole library"),
    FrameNumberDescription(key="repeat_days", name="Repeat window", icon="mdi:calendar-refresh", native_min_value=0, native_max_value=365,
                           native_step=1, native_unit_of_measurement=UnitOfTime.DAYS, mode=NumberMode.BOX,
                           entity_category=EntityCategory.CONFIG, value=lambda d: d.get("repeat_days"),
                           call=lambda api, v: api.settings(repeat_days=v)),
    FrameNumberDescription(key="min_score", name="Minimum vision score (all displays)", icon="mdi:star-half-full", native_min_value=1,
                           native_max_value=10, native_step=1, mode=NumberMode.BOX, entity_category=EntityCategory.CONFIG,
                           value=lambda d: d.get("min_score"), call=lambda api, v: api.min_score(v)),
)


class FrameNumber(FrameEntity, NumberEntity):
    entity_description: FrameNumberDescription

    def __init__(self, coordinator: FrameCoordinator, description: FrameNumberDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value(self.coordinator.data) if self.coordinator.data else None

    async def async_set_native_value(self, value: float) -> None:
        await self._push(self.entity_description.call(self.coordinator.api, int(value)))
