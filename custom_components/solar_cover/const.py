"""Constants for the Solar Cover integration."""

from enum import StrEnum

DOMAIN = "solar_cover"

ENTRY_TYPE_INTEGRATION = "integration"
ENTRY_TYPE_ZONE = "zone"

# Integration-level config keys
CONF_WEATHER_ENTITY = "weather_entity"
CONF_WIND_THRESHOLD = "wind_threshold"
CONF_MIN_TEMP = "min_temp"
CONF_INACTIVE_POSITION = "inactive_position"
CONF_OVERRIDE_DURATION = "override_duration"
CONF_CLOUD_ENTITY = "cloud_entity"
CONF_CLOUD_THRESHOLD = "cloud_threshold"
CONF_RADIATION_ENTITY = "radiation_entity"
CONF_RADIATION_THRESHOLD = "radiation_threshold"

# Zone config keys
CONF_COVER_ENTITIES = "cover_entities"
CONF_COVER_TYPE = "cover_type"
CONF_AZIMUTH = "azimuth"
CONF_FOV_LEFT = "fov_left"
CONF_FOV_RIGHT = "fov_right"
CONF_ELEVATION_THRESHOLD = "elevation_threshold"
CONF_INACTIVE_POSITION_OVERRIDE = "inactive_position_override"

# Vertical blind geometry
CONF_WINDOW_HEIGHT = "window_height"
CONF_GLARE_DEPTH = "glare_depth"

# Horizontal awning geometry
CONF_ATTACH_HEIGHT = "attach_height"
CONF_AWN_LENGTH = "awn_length"
CONF_AWN_ANGLE = "awn_angle"

# Tilt geometry
CONF_SLAT_WIDTH = "slat_width"
CONF_SLAT_SPACING = "slat_spacing"
CONF_TILT_RANGE = "tilt_range"

# Advanced
CONF_MIN_POSITION = "min_position"
CONF_MAX_POSITION = "max_position"
CONF_HYSTERESIS = "hysteresis"
CONF_OVERRIDE_DURATION_OVERRIDE = "override_duration_override"


class CoverType(StrEnum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    TILT = "tilt"


class TiltRange(StrEnum):
    SINGLE = "single"
    BIDIRECTIONAL = "bidirectional"


class Intent(StrEnum):
    SHADING = "shading"
    INACTIVE_SUN_LOW = "inactive_sun_low"
    INACTIVE_OUTSIDE_FOV = "inactive_outside_fov"
    INACTIVE_WEATHER = "inactive_weather"
    INACTIVE_OVERCAST = "inactive_overcast"
    MANUAL_OVERRIDE = "manual_override"


DEFAULT_INACTIVE_POSITION: int = 0
DEFAULT_OVERRIDE_DURATION: int = 120
DEFAULT_HYSTERESIS: float = 3.0
DEFAULT_ELEVATION_THRESHOLD_FACTOR: float = 0.6
UPDATE_INTERVAL_MINUTES: int = 5
