"""Constants for the MAX! Cube Manager integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "max_cube_manager"
DEFAULT_HOST = "max_cube_manager"
API_PORT = 62910
UPDATE_INTERVAL = timedelta(seconds=60)
PLATFORMS = [Platform.CLIMATE]
