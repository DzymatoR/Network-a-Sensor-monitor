"""Network connectivity monitoring via ping"""

import logging
import statistics
from typing import Dict, Any, Optional, List
from datetime import datetime
import subprocess
import re

logger = logging.getLogger(__name__)


class NetworkMonitor:
    """Monitor network connectivity using ping"""

    def __init__(self, timeout: int = 2):
        self.timeout = timeout

    def ping(
        self, target: str, count: int = 1, target_type: str = "unknown"
    ) -> Dict[str, Any]:
        """
        Ping a target and return results.

        Args:
            target: IP address or hostname
            count: Number of ping packets to send
            target_type: Type of target ('gateway', 'internet', 'sensor')

        Returns:
            Dict with ping results
        """
        result = {
            "timestamp": datetime.utcnow(),
            "target": target,
            "target_type": target_type,
            "is_reachable": False,
            "latency_ms": None,
            "packet_loss": 100.0,
            "ttl": None,
            "min_latency": None,
            "max_latency": None,
            "avg_latency": None,
            "jitter": None,
        }

        try:
            # Use ping command
            cmd = [
                "ping",
                "-c",
                str(count),
                "-W",
                str(self.timeout),
                target,
            ]

            output = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, timeout=self.timeout * count + 5
            ).decode("utf-8")

            # Parse output
            # Example: 64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=13.4 ms
            latencies = []
            ttls = []

            for line in output.split("\n"):
                if "bytes from" in line or "from" in line:
                    # Extract latency
                    time_match = re.search(r"time=(\d+\.?\d*)", line)
                    if time_match:
                        latencies.append(float(time_match.group(1)))

                    # Extract TTL
                    ttl_match = re.search(r"ttl=(\d+)", line)
                    if ttl_match:
                        ttls.append(int(ttl_match.group(1)))

            # Parse statistics line
            # Example: 4 packets transmitted, 4 received, 0% packet loss, time 3004ms
            stats_match = re.search(
                r"(\d+) packets transmitted, (\d+) received, (\d+)% packet loss",
                output,
            )
            if stats_match:
                transmitted = int(stats_match.group(1))
                received = int(stats_match.group(2))
                packet_loss = float(stats_match.group(3))

                result["packet_loss"] = packet_loss
                result["is_reachable"] = received > 0

            # Parse rtt line
            # Example: rtt min/avg/max/mdev = 13.329/13.501/13.673/0.141 ms
            rtt_match = re.search(
                r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output
            )
            if rtt_match:
                result["min_latency"] = float(rtt_match.group(1))
                result["avg_latency"] = float(rtt_match.group(2))
                result["max_latency"] = float(rtt_match.group(3))
                result["jitter"] = float(rtt_match.group(4))

            if latencies:
                result["latency_ms"] = statistics.mean(latencies)
                if len(latencies) > 1 and not result["jitter"]:
                    # Calculate jitter as standard deviation if not provided
                    result["jitter"] = statistics.stdev(latencies)

            if ttls:
                result["ttl"] = ttls[0]

        except subprocess.CalledProcessError as e:
            # Ping failed (host unreachable, timeout, etc.)
            output = e.output.decode("utf-8") if e.output else ""
            logger.debug(f"Ping to {target} failed: {output}")
            result["is_reachable"] = False

        except subprocess.TimeoutExpired:
            logger.warning(f"Ping to {target} timed out")
            result["is_reachable"] = False

        except Exception as e:
            logger.error(f"Error pinging {target}: {e}", exc_info=True)
            result["is_reachable"] = False

        return result

    def check_dns_resolution(self, hostname: str) -> Dict[str, Any]:
        """
        Check if DNS resolution is working.

        Args:
            hostname: Hostname to resolve

        Returns:
            Dict with resolution time and success status
        """
        result = {
            "timestamp": datetime.utcnow(),
            "hostname": hostname,
            "resolved": False,
            "resolution_time_ms": None,
            "ip_address": None,
        }

        try:
            import time
            import socket

            start = time.time()
            ip = socket.gethostbyname(hostname)
            end = time.time()

            result["resolved"] = True
            result["ip_address"] = ip
            result["resolution_time_ms"] = (end - start) * 1000

        except socket.gaierror as e:
            logger.debug(f"DNS resolution failed for {hostname}: {e}")
        except Exception as e:
            logger.error(f"Error resolving {hostname}: {e}", exc_info=True)

        return result

    def continuous_ping(
        self, target: str, interval: int = 5, target_type: str = "unknown"
    ):
        """
        Generator that continuously pings a target.

        Args:
            target: IP address or hostname
            interval: Seconds between pings
            target_type: Type of target

        Yields:
            Ping results
        """
        import time

        while True:
            result = self.ping(target, count=1, target_type=target_type)
            yield result
            time.sleep(interval)

    @staticmethod
    def calculate_jitter(latencies: List[float]) -> Optional[float]:
        """Calculate jitter (variation in latency) from a list of latencies"""
        if len(latencies) < 2:
            return None
        return statistics.stdev(latencies)
