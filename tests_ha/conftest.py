from pathlib import Path

import pytest
from pytest_homeassistant_custom_component import common

ROOT = Path(__file__).resolve().parent.parent
# the plugin's own config dir has its own `custom_components`; point HA at the repo root so ours loads
common.get_test_config_dir = lambda *add: str(ROOT.joinpath(*add))


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


OPTIONS = {"people": ["Kari", "Ola"], "albums": ["Holiday"], "places": ["Norway", "Oslo, Norway"]}


@pytest.fixture(autouse=True)
def _options(aioclient_mock):
    aioclient_mock.get("http://frame.test:8099/options", json=OPTIONS)
