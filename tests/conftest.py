"""Common test fixtures for Busch-Radio iNet integration tests."""

import pytest
import sys
import os

# Add project root to Python path so custom_components is importable
project_root = os.path.dirname(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations in Home Assistant."""
    return enable_custom_integrations


@pytest.fixture
def device_host() -> str:
    return "192.168.1.179"


@pytest.fixture
def device_port() -> int:
    return 4244


@pytest.fixture
def device_serial() -> str:
    return "78C40E33745C"


@pytest.fixture
def config_entry_data(device_host, device_port):
    return {
        "host": device_host,
        "port": device_port,
        "name": "Busch-Radio iNet",
    }


@pytest.fixture
def mock_config_entry(config_entry_data, device_serial):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    return MockConfigEntry(
        domain="busch_radio_inet",
        data=config_entry_data,
        unique_id=device_serial,
        version=1,
    )
