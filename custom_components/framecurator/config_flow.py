"""Config flow: ask for the API address and token, and check them."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME, CONF_TOKEN, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify

from .api import AuthError, FrameApi
from .const import CONF_DEVICE, CONF_HEIGHT, CONF_WIDTH, DEFAULT_SIZE, DOMAIN


class FrameConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input:
            url, name = user_input[CONF_URL].rstrip("/"), user_input[CONF_NAME].strip()
            device = slugify(name, separator="-")[:32]  # the API only accepts [a-z0-9_-]
            size = (user_input[CONF_WIDTH], user_input[CONF_HEIGHT])
            if not device:
                errors[CONF_NAME] = "invalid_name"
            else:
                await self.async_set_unique_id(f"{url}|{device}")
                self._abort_if_unique_id_configured()
                try:
                    await FrameApi(async_get_clientsession(self.hass), url, user_input[CONF_TOKEN], device, size).state()
                except AuthError:
                    errors["base"] = "invalid_auth"
                except Exception:  # noqa: BLE001 - any failure here means we cannot talk to the API
                    errors["base"] = "cannot_connect"
                else:
                    data = {CONF_URL: url, CONF_TOKEN: user_input[CONF_TOKEN], CONF_DEVICE: device,
                            CONF_WIDTH: size[0], CONF_HEIGHT: size[1]}
                    return self.async_create_entry(title=name, data=data)
        schema = vol.Schema({
            vol.Required(CONF_NAME, default="Wallpanel"): str,
            vol.Required(CONF_URL): str,
            vol.Required(CONF_TOKEN): str,
            vol.Required(CONF_WIDTH, default=DEFAULT_SIZE[0]): vol.All(int, vol.Range(min=320, max=4096)),
            vol.Required(CONF_HEIGHT, default=DEFAULT_SIZE[1]): vol.All(int, vol.Range(min=320, max=4096)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
