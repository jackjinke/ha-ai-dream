"""Config flow for AI Dream."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import AiDreamApi, AiDreamApiError, AiDreamAuthError, Device
from .const import (
    CONF_DEVICE_NAME,
    CONF_DID,
    CONF_ENABLE_WAIST,
    CONF_GID,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_PRODUCT_CODE,
    CONF_SCAN_INTERVAL,
    CONF_SMS_CODE,
    CONF_TOKEN,
    CONF_UID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class AiDreamConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the AI Dream login and device selection."""

    VERSION = 1

    def __init__(self) -> None:
        self._api: AiDreamApi | None = None
        self._phone: str | None = None
        self._password: str | None = None
        self._devices: list[Device] = []
        self._reauth_entry = None

    @property
    def api(self) -> AiDreamApi:
        if self._api is None:
            self._api = AiDreamApi(async_get_clientsession(self.hass))
        return self._api

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AiDreamOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._phone = str(user_input[CONF_PHONE]).strip()
            if user_input["method"] == "password":
                return await self.async_step_password()
            try:
                await self.api.send_sms_code(self._phone)
            except AiDreamApiError as err:
                _LOGGER.debug("Sending SMS failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_sms()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PHONE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEL)
                    ),
                    vol.Required("method", default="sms"): SelectSelector(
                        SelectSelectorConfig(
                            options=["sms", "password"],
                            translation_key="login_method",
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._phone is not None
            try:
                await self.api.login_sms(
                    self._phone, str(user_input[CONF_SMS_CODE]).strip()
                )
            except AiDreamAuthError:
                errors["base"] = "invalid_auth"
            except AiDreamApiError as err:
                _LOGGER.debug("SMS login failed: %s", err)
                errors["base"] = (
                    "invalid_auth" if err.code == "1300" else "cannot_connect"
                )
            else:
                return await self._async_finish_login()

        return self.async_show_form(
            step_id="sms",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SMS_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            ),
            description_placeholders={"phone": self._phone or ""},
            errors=errors,
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._phone is not None
            self._password = str(user_input[CONF_PASSWORD])
            try:
                await self.api.login_password(self._phone, self._password)
            except AiDreamAuthError:
                errors["base"] = "invalid_auth"
            except AiDreamApiError as err:
                _LOGGER.debug("Password login failed: %s", err)
                errors["base"] = (
                    "invalid_auth" if err.code == "1300" else "cannot_connect"
                )
            else:
                return await self._async_finish_login()

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"phone": self._phone or ""},
            errors=errors,
        )

    async def _async_finish_login(self) -> ConfigFlowResult:
        try:
            self._devices = await self.api.get_devices()
        except AiDreamAuthError:
            return self.async_abort(reason="cannot_connect")
        except AiDreamApiError as err:
            _LOGGER.debug("Loading devices failed: %s", err)
            return self.async_abort(reason="cannot_connect")

        if not self._devices:
            return self.async_abort(reason="no_devices")
        if len(self._devices) == 1:
            return await self._async_create_entry(self._devices[0])
        return await self.async_step_device()

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            did = int(user_input[CONF_DID])
            device = next((item for item in self._devices if item.did == did), None)
            if device is None:
                return self.async_abort(reason="no_devices")
            return await self._async_create_entry(device)

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=str(device.did),
                                    label=f"{device.name} ({device.did})",
                                )
                                for device in self._devices
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def _async_create_entry(self, device: Device) -> ConfigFlowResult:
        await self.async_set_unique_id(str(device.did))
        self._abort_if_unique_id_configured()

        data = {
            CONF_TOKEN: self.api.token,
            CONF_UID: self.api.uid,
            CONF_GID: self.api.gid,
            CONF_PHONE: self._phone,
            CONF_DID: device.did,
            CONF_DEVICE_NAME: device.name,
            CONF_PRODUCT_CODE: device.product_code,
        }
        if self._password:
            data[CONF_PASSWORD] = self._password

        return self.async_create_entry(title=device.name, data=data)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._phone = entry_data.get(CONF_PHONE)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._phone is not None
            try:
                await self.api.send_sms_code(self._phone)
            except AiDreamApiError as err:
                _LOGGER.debug("Sending SMS failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_reauth_sms()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"phone": self._phone or ""},
            errors=errors,
        )

    async def async_step_reauth_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._phone is not None and self._reauth_entry is not None
            try:
                await self.api.login_sms(
                    self._phone, str(user_input[CONF_SMS_CODE]).strip()
                )
            except AiDreamAuthError:
                errors["base"] = "invalid_auth"
            except AiDreamApiError as err:
                _LOGGER.debug("Reauth failed: %s", err)
                errors["base"] = (
                    "invalid_auth" if err.code == "1300" else "cannot_connect"
                )
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_TOKEN: self.api.token,
                        CONF_UID: self.api.uid,
                        CONF_GID: self.api.gid,
                    },
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_sms",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SMS_CODE): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    )
                }
            ),
            description_placeholders={"phone": self._phone or ""},
            errors=errors,
        )


class AiDreamOptionsFlow(OptionsFlow):
    """Tune polling and optional axes."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = dict(self.config_entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, 30),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=10,
                            max=600,
                            step=5,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Optional(
                        CONF_ENABLE_WAIST,
                        default=options.get(CONF_ENABLE_WAIST, False),
                    ): BooleanSelector(),
                }
            ),
        )
