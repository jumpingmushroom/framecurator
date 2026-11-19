from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FrameConfigEntry
from .entity import FrameEntity

WHY_SHOWN = {"on_this_day": "On this day", "favorites_picks": "Favorite or pick", "recent_30d": "Recent", "library": "From the library",
             "previous": "Earlier photo"}


@dataclass(frozen=True, kw_only=True)
class FrameSensorDescription(SensorEntityDescription):
    value: Callable[[dict], Any]


def _diag(**kw) -> FrameSensorDescription:
    return FrameSensorDescription(entity_category=EntityCategory.DIAGNOSTIC, **kw)


SENSORS = (
    # the caption is the one a card needs; the rest are diagnostic so the device page stays calm
    FrameSensorDescription(key="caption", name="Caption", icon="mdi:subtitles-outline", value=lambda d: d.get("caption")),
    _diag(key="date", name="Date", device_class=SensorDeviceClass.DATE, value=lambda d: date.fromisoformat(d["date"])),
    _diag(key="place", name="Place", icon="mdi:map-marker", value=lambda d: d.get("place")),
    _diag(key="people", name="People", icon="mdi:account-multiple", value=lambda d: ", ".join(d.get("people") or []) or None),
    _diag(key="years_ago", name="Years ago", icon="mdi:history", value=lambda d: d.get("years_ago")),
    _diag(key="next_change", name="Next change", device_class=SensorDeviceClass.TIMESTAMP,
          value=lambda d: datetime.fromisoformat(d["next_change_at"]) if d.get("next_change_at") else None),  # null while paused
    _diag(key="why_shown", name="Why shown", icon="mdi:help-circle-outline", value=lambda d: WHY_SHOWN.get(d.get("bucket"))),
)


async def async_setup_entry(hass: HomeAssistant, entry: FrameConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(FrameSensor(entry.runtime_data, d) for d in SENSORS)


class FrameSensor(FrameEntity, SensorEntity):
    entity_description: FrameSensorDescription

    def __init__(self, coordinator, description: FrameSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value(self.coordinator.data) if self.coordinator.data else None
