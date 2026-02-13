"""WiFi connection monitoring"""

import logging
import re
import subprocess
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class WiFiMonitor:
    """Monitor WiFi connection status and signal quality"""

    def __init__(self, interface: str = "wlan0"):
        self.interface = interface

    def get_wifi_status(self) -> Dict[str, Any]:
        """
        Get current WiFi status including RSSI, link quality, and connection info.
        Returns dict with WiFi metrics or None values if disconnected/unavailable.
        """
        status = {
            "timestamp": datetime.utcnow(),
            "interface": self.interface,
            "ssid": None,
            "rssi": None,
            "link_quality": None,
            "frequency": None,
            "channel": None,
            "is_connected": False,
            "ip_address": None,
        }

        try:
            # Check if interface exists and is up
            ip_output = subprocess.check_output(
                ["ip", "link", "show", self.interface],
                stderr=subprocess.STDOUT,
                timeout=5,
            ).decode("utf-8")

            if "state UP" not in ip_output and "state UNKNOWN" not in ip_output:
                logger.warning(f"Interface {self.interface} is down")
                return status

            # Get IP address
            try:
                ip_addr_output = subprocess.check_output(
                    ["ip", "-4", "addr", "show", self.interface],
                    stderr=subprocess.STDOUT,
                    timeout=5,
                ).decode("utf-8")
                ip_match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ip_addr_output)
                if ip_match:
                    status["ip_address"] = ip_match.group(1)
            except Exception as e:
                logger.debug(f"Could not get IP address: {e}")

            # Try iwconfig first (older systems)
            try:
                iwconfig_output = subprocess.check_output(
                    ["iwconfig", self.interface],
                    stderr=subprocess.STDOUT,
                    timeout=5,
                ).decode("utf-8")

                # Parse iwconfig output
                essid_match = re.search(r'ESSID:"([^"]+)"', iwconfig_output)
                if essid_match:
                    status["ssid"] = essid_match.group(1)
                    status["is_connected"] = True

                # Signal level
                signal_match = re.search(r"Signal level=(-?\d+) dBm", iwconfig_output)
                if signal_match:
                    status["rssi"] = int(signal_match.group(1))

                # Link Quality
                quality_match = re.search(r"Link Quality=(\d+)/(\d+)", iwconfig_output)
                if quality_match:
                    current = int(quality_match.group(1))
                    maximum = int(quality_match.group(2))
                    status["link_quality"] = (current / maximum) * 100

                # Frequency
                freq_match = re.search(r"Frequency:(\d+\.?\d*) GHz", iwconfig_output)
                if freq_match:
                    status["frequency"] = float(freq_match.group(1))

            except subprocess.CalledProcessError:
                logger.debug("iwconfig not available, trying iw")

            # Try iw (newer systems)
            try:
                iw_output = subprocess.check_output(
                    ["iw", "dev", self.interface, "link"],
                    stderr=subprocess.STDOUT,
                    timeout=5,
                ).decode("utf-8")

                if "Not connected" not in iw_output:
                    status["is_connected"] = True

                    # SSID
                    ssid_match = re.search(r"SSID: (.+)", iw_output)
                    if ssid_match:
                        status["ssid"] = ssid_match.group(1).strip()

                    # Signal strength
                    signal_match = re.search(r"signal: (-?\d+) dBm", iw_output)
                    if signal_match:
                        status["rssi"] = int(signal_match.group(1))

                    # Frequency
                    freq_match = re.search(r"freq: (\d+)", iw_output)
                    if freq_match:
                        freq_mhz = int(freq_match.group(1))
                        status["frequency"] = freq_mhz / 1000.0
                        status["channel"] = self._freq_to_channel(freq_mhz)

            except subprocess.CalledProcessError as e:
                logger.debug(f"iw not available: {e}")

            # Fallback: try /proc/net/wireless
            if status["rssi"] is None:
                try:
                    with open("/proc/net/wireless", "r") as f:
                        lines = f.readlines()
                        for line in lines:
                            if self.interface in line:
                                parts = line.split()
                                if len(parts) >= 4:
                                    # Link quality
                                    link_quality = int(parts[2].rstrip("."))
                                    status["link_quality"] = (link_quality / 70) * 100
                                    # Signal level (dBm)
                                    signal_level = int(parts[3].rstrip("."))
                                    status["rssi"] = signal_level - 256 if signal_level > 127 else signal_level
                except Exception as e:
                    logger.debug(f"Could not read /proc/net/wireless: {e}")

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout while checking WiFi status on {self.interface}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error checking WiFi status: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in WiFi monitoring: {e}", exc_info=True)

        return status

    @staticmethod
    def _freq_to_channel(freq_mhz: int) -> Optional[int]:
        """Convert frequency in MHz to WiFi channel number"""
        if 2412 <= freq_mhz <= 2484:
            # 2.4 GHz band
            if freq_mhz == 2484:
                return 14
            return (freq_mhz - 2412) // 5 + 1
        elif 5170 <= freq_mhz <= 5825:
            # 5 GHz band
            return (freq_mhz - 5000) // 5
        return None

    def get_signal_quality_rating(self, rssi: Optional[int]) -> str:
        """
        Convert RSSI to human-readable quality rating.
        """
        if rssi is None:
            return "Unknown"
        if rssi >= -50:
            return "Excellent"
        elif rssi >= -60:
            return "Good"
        elif rssi >= -70:
            return "Fair"
        elif rssi >= -80:
            return "Weak"
        else:
            return "Very Weak"
