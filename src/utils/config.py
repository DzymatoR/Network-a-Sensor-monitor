"""Configuration loading and parsing"""

import os
import logging
import yaml
from typing import Dict, Any, Optional
from datetime import timedelta

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to config.yml

    Returns:
        Configuration dictionary
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        # Apply environment variable overrides
        _apply_env_overrides(config)

        # Validate configuration
        _validate_config(config)

        logger.info(f"Configuration loaded from {config_path}")
        return config

    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in configuration file: {e}")
    except Exception as e:
        raise RuntimeError(f"Error loading configuration: {e}")


def _apply_env_overrides(config: Dict[str, Any]):
    """Apply environment variable overrides to config"""
    # Override MQTT credentials from environment if present
    mqtt_user = os.getenv("MQTT_USERNAME")
    mqtt_pass = os.getenv("MQTT_PASSWORD")

    if mqtt_user or mqtt_pass:
        for sensor in config.get("sensors", []):
            if sensor.get("type") == "mqtt":
                if mqtt_user:
                    sensor["username"] = mqtt_user
                if mqtt_pass:
                    sensor["password"] = mqtt_pass


def _validate_config(config: Dict[str, Any]):
    """Validate required configuration fields"""
    required_sections = ["wifi", "gateway", "sensors", "monitoring", "database"]

    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required configuration section: {section}")

    # Validate WiFi config
    if "interface" not in config["wifi"]:
        raise ValueError("WiFi interface not specified")

    # Validate gateway
    if "ip" not in config["gateway"]:
        raise ValueError("Gateway IP not specified")

    # Validate sensors
    if not isinstance(config["sensors"], list) or len(config["sensors"]) == 0:
        logger.warning("No sensors defined in configuration")

    for sensor in config.get("sensors", []):
        if "name" not in sensor or "ip" not in sensor or "type" not in sensor:
            raise ValueError(f"Invalid sensor configuration: {sensor}")

        if sensor["type"] not in ["ping", "mqtt", "http"]:
            raise ValueError(f"Invalid sensor type: {sensor['type']}")


def parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    Parse duration string to timedelta.

    Supported formats:
    - "1h", "2h" -> hours
    - "30m", "45m" -> minutes
    - "1d", "7d" -> days
    - "continuous" -> None (infinite)

    Args:
        duration_str: Duration string

    Returns:
        timedelta object or None for continuous
    """
    if duration_str.lower() == "continuous":
        return None

    try:
        duration_str = duration_str.strip().lower()

        if duration_str.endswith("h"):
            hours = int(duration_str[:-1])
            return timedelta(hours=hours)
        elif duration_str.endswith("m"):
            minutes = int(duration_str[:-1])
            return timedelta(minutes=minutes)
        elif duration_str.endswith("d"):
            days = int(duration_str[:-1])
            return timedelta(days=days)
        elif duration_str.endswith("s"):
            seconds = int(duration_str[:-1])
            return timedelta(seconds=seconds)
        else:
            # Try to parse as integer seconds
            seconds = int(duration_str)
            return timedelta(seconds=seconds)

    except (ValueError, AttributeError):
        raise ValueError(f"Invalid duration format: {duration_str}")
