from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FrameCoordinator
from .const import DOMAIN


class FrameEntity(CoordinatorEntity[FrameCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: FrameCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)}, name=coordinator.config_entry.title)

    async def _push(self, call) -> None:
        """Run an API call and publish its reply as the new state, so the UI updates without waiting for the next poll."""
        self.coordinator.async_set_updated_data(await call)
