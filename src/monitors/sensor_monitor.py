"""IoT sensor monitoring (ping, MQTT, HTTP)"""

import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime
import subprocess

logger = logging.getLogger(__name__)


class SensorMonitor:
    """Monitor IoT sensors using various protocols"""

    def __init__(self):
        pass

    def check_ping(
        self, ip: str, timeout: int = 2
    ) -> Dict[str, Any]:
        """
        Check sensor availability via ping.

        Args:
            ip: Sensor IP address
            timeout: Timeout in seconds

        Returns:
            Dict with check results
        """
        result = {
            "timestamp": datetime.utcnow(),
            "is_available": False,
            "latency_ms": None,
            "error_message": None,
        }

        try:
            cmd = ["ping", "-c", "1", "-W", str(timeout), ip]
            output = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, timeout=timeout + 2
            ).decode("utf-8")

            # Extract latency
            import re

            time_match = re.search(r"time=(\d+\.?\d*)", output)
            if time_match:
                result["latency_ms"] = float(time_match.group(1))
                result["is_available"] = True

        except subprocess.CalledProcessError:
            result["error_message"] = "Host unreachable"
        except subprocess.TimeoutExpired:
            result["error_message"] = "Ping timeout"
        except Exception as e:
            result["error_message"] = str(e)
            logger.error(f"Error pinging sensor {ip}: {e}", exc_info=True)

        return result

    def check_mqtt(
        self,
        ip: str,
        port: int = 1883,
        timeout: int = 5,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check MQTT broker availability.

        Args:
            ip: Broker IP address
            port: MQTT port
            timeout: Connection timeout
            username: Optional MQTT username
            password: Optional MQTT password

        Returns:
            Dict with check results
        """
        result = {
            "timestamp": datetime.utcnow(),
            "is_available": False,
            "latency_ms": None,
            "status_code": None,  # MQTT CONNACK return code
            "error_message": None,
        }

        try:
            import paho.mqtt.client as mqtt

            connect_result = {"success": False, "rc": None, "time": None}

            def on_connect(client, userdata, flags, rc):
                userdata["success"] = rc == 0
                userdata["rc"] = rc

            client = mqtt.Client(userdata=connect_result)
            client.on_connect = on_connect

            if username and password:
                client.username_pw_set(username, password)

            start = time.time()
            client.connect(ip, port, keepalive=timeout)
            client.loop_start()

            # Wait for connection
            wait_time = 0
            while wait_time < timeout:
                if connect_result["rc"] is not None:
                    break
                time.sleep(0.1)
                wait_time += 0.1

            client.loop_stop()
            client.disconnect()
            end = time.time()

            if connect_result["success"]:
                result["is_available"] = True
                result["latency_ms"] = (end - start) * 1000
                result["status_code"] = 0
            else:
                result["status_code"] = connect_result["rc"]
                result["error_message"] = self._mqtt_error_string(
                    connect_result["rc"]
                )

        except ImportError:
            result["error_message"] = "paho-mqtt library not installed"
            logger.warning("paho-mqtt not available for MQTT checks")
        except Exception as e:
            result["error_message"] = str(e)
            logger.error(f"Error checking MQTT broker {ip}:{port}: {e}", exc_info=True)

        return result

    def check_http(
        self,
        ip: str,
        port: int = 80,
        path: str = "/",
        timeout: int = 5,
        https: bool = False,
    ) -> Dict[str, Any]:
        """
        Check HTTP endpoint availability.

        Args:
            ip: Server IP address
            port: HTTP port
            path: URL path to check
            timeout: Request timeout
            https: Use HTTPS instead of HTTP

        Returns:
            Dict with check results
        """
        result = {
            "timestamp": datetime.utcnow(),
            "is_available": False,
            "latency_ms": None,
            "status_code": None,
            "error_message": None,
        }

        try:
            import urllib.request
            import urllib.error

            protocol = "https" if https else "http"
            url = f"{protocol}://{ip}:{port}{path}"

            start = time.time()
            response = urllib.request.urlopen(url, timeout=timeout)
            end = time.time()

            result["status_code"] = response.getcode()
            result["is_available"] = 200 <= result["status_code"] < 300
            result["latency_ms"] = (end - start) * 1000

        except urllib.error.HTTPError as e:
            result["status_code"] = e.code
            result["error_message"] = f"HTTP {e.code}"
            # Some endpoints return 4xx/5xx but are still "available"
            result["latency_ms"] = time.time() - start if 'start' in locals() else None

        except urllib.error.URLError as e:
            result["error_message"] = str(e.reason)
        except Exception as e:
            result["error_message"] = str(e)
            logger.error(
                f"Error checking HTTP endpoint {ip}:{port}{path}: {e}", exc_info=True
            )

        return result

    @staticmethod
    def _mqtt_error_string(rc: Optional[int]) -> str:
        """Convert MQTT return code to error string"""
        if rc is None:
            return "Connection timeout"

        errors = {
            0: "Connection successful",
            1: "Incorrect protocol version",
            2: "Invalid client identifier",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized",
        }
        return errors.get(rc, f"Unknown error (code {rc})")
