"""Automatic recommendation generation based on monitoring data"""

import logging
from typing import List, Dict, Any
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """Generate recommendations based on monitoring data"""

    def __init__(self, db):
        self.db = db

    def generate_recommendations(
        self, start_time: datetime, end_time: datetime
    ) -> List[str]:
        """
        Generate recommendations based on data analysis.

        Args:
            start_time: Analysis start time
            end_time: Analysis end time

        Returns:
            List of recommendation strings
        """
        recommendations = []

        # Analyze WiFi signal strength
        wifi_recs = self._analyze_wifi_signal(start_time, end_time)
        recommendations.extend(wifi_recs)

        # Analyze WiFi disconnections
        disconn_recs = self._analyze_wifi_disconnections(start_time, end_time)
        recommendations.extend(disconn_recs)

        # Analyze sensor reliability
        sensor_recs = self._analyze_sensor_reliability(start_time, end_time)
        recommendations.extend(sensor_recs)

        # Analyze network issues
        network_recs = self._analyze_network_issues(start_time, end_time)
        recommendations.extend(network_recs)

        # Analyze time-based patterns
        time_recs = self._analyze_time_patterns(start_time, end_time)
        recommendations.extend(time_recs)

        if not recommendations:
            recommendations.append("✅ No major issues detected. System is operating normally.")

        return recommendations

    def _analyze_wifi_signal(
        self, start_time: datetime, end_time: datetime
    ) -> List[str]:
        """Analyze WiFi signal strength and provide recommendations"""
        recs = []
        metrics = self.db.get_wifi_metrics(start_time, end_time)

        if not metrics:
            return recs

        # Calculate average RSSI
        rssi_values = [m.rssi for m in metrics if m.rssi is not None]
        if not rssi_values:
            return recs

        avg_rssi = sum(rssi_values) / len(rssi_values)
        min_rssi = min(rssi_values)

        # Check for weak signal
        if avg_rssi < -75:
            recs.append(
                f"⚠️ WiFi signal is weak (average {avg_rssi:.0f} dBm). "
                "Consider moving the access point closer or adding a WiFi repeater."
            )
        elif avg_rssi < -65:
            recs.append(
                f"⚠️ WiFi signal could be improved (average {avg_rssi:.0f} dBm). "
                "Consider repositioning the Raspberry Pi or access point for better signal."
            )

        if min_rssi < -85:
            recs.append(
                f"⚠️ WiFi signal drops to very weak levels ({min_rssi:.0f} dBm at worst). "
                "This may cause intermittent connectivity issues."
            )

        # Check for signal variation
        if len(rssi_values) > 10:
            import statistics

            rssi_stdev = statistics.stdev(rssi_values)
            if rssi_stdev > 10:
                recs.append(
                    f"⚠️ WiFi signal varies significantly (±{rssi_stdev:.1f} dBm). "
                    "This may indicate interference or physical obstruction. "
                    "Try changing the WiFi channel or reducing interference sources."
                )

        # Analyze by time of day
        hourly_rssi = defaultdict(list)
        for m in metrics:
            if m.rssi:
                hourly_rssi[m.timestamp.hour].append(m.rssi)

        weak_hours = []
        for hour, rssi_list in hourly_rssi.items():
            avg = sum(rssi_list) / len(rssi_list)
            if avg < -75:
                weak_hours.append(hour)

        if weak_hours and len(weak_hours) < 12:
            hours_str = ", ".join(f"{h:02d}:00" for h in sorted(weak_hours))
            recs.append(
                f"⚠️ WiFi signal is particularly weak during: {hours_str}. "
                "This may indicate time-based interference (e.g., microwave usage, neighboring WiFi activity)."
            )

        return recs

    def _analyze_wifi_disconnections(
        self, start_time: datetime, end_time: datetime
    ) -> List[str]:
        """Analyze WiFi disconnection events"""
        recs = []
        metrics = self.db.get_wifi_metrics(start_time, end_time)

        if not metrics:
            return recs

        # Count disconnections
        disconnections = sum(1 for m in metrics if not m.is_connected)
        total = len(metrics)
        disconn_rate = (disconnections / total * 100) if total > 0 else 0

        if disconnections > 0:
            if disconn_rate > 5:
                recs.append(
                    f"⚠️ WiFi disconnected {disconnections} times ({disconn_rate:.1f}% of checks). "
                    "Check wpa_supplicant/NetworkManager configuration and consider using static IP. "
                    "Review system logs for kernel WiFi driver errors."
                )
            elif disconnections > 3:
                recs.append(
                    f"⚠️ WiFi disconnected {disconnections} times. "
                    "Monitor for recurring patterns and consider investigating router logs."
                )

        return recs

    def _analyze_sensor_reliability(
        self, start_time: datetime, end_time: datetime
    ) -> List[str]:
        """Analyze individual sensor reliability"""
        recs = []

        # Get all unique sensors
        all_checks = self.db.get_sensor_checks(start_time=start_time, end_time=end_time)

        sensors = {}
        for check in all_checks:
            if check.sensor_name not in sensors:
                sensors[check.sensor_name] = []
            sensors[check.sensor_name].append(check)

        for sensor_name, checks in sensors.items():
            if not checks:
                continue

            failed = sum(1 for c in checks if not c.is_available)
            total = len(checks)
            failure_rate = (failed / total * 100) if total > 0 else 0

            # Check if failures correlate with WiFi issues
            wifi_metrics = self.db.get_wifi_metrics(start_time, end_time)
            wifi_down_times = [m.timestamp for m in wifi_metrics if not m.is_connected]

            correlated_failures = 0
            for check in checks:
                if not check.is_available:
                    # Check if WiFi was down within 1 minute of this failure
                    for wifi_time in wifi_down_times:
                        if abs((check.timestamp - wifi_time).total_seconds()) < 60:
                            correlated_failures += 1
                            break

            independent_failures = failed - correlated_failures

            if independent_failures > 0 and failure_rate > 10:
                recs.append(
                    f"⚠️ Sensor '{sensor_name}' has {independent_failures} failures "
                    f"({failure_rate:.1f}% of checks) independent of WiFi issues. "
                    "Check the sensor device, power supply, and network configuration."
                )
            elif failure_rate > 20:
                recs.append(
                    f"⚠️ Sensor '{sensor_name}' has {failed} failures ({failure_rate:.1f}% of checks). "
                    f"{correlated_failures} appear correlated with WiFi issues."
                )

        return recs

    def _analyze_network_issues(
        self, start_time: datetime, end_time: datetime
    ) -> List[str]:
        """Analyze gateway and internet connectivity"""
        recs = []

        # Get ping results for gateway and internet
        ping_results = self.db.get_ping_results(start_time=start_time, end_time=end_time)

        gateway_results = [r for r in ping_results if r.target_type == "gateway"]
        internet_results = [r for r in ping_results if r.target_type == "internet"]

        # Analyze gateway
        if gateway_results:
            failed = sum(1 for r in gateway_results if not r.is_reachable)
            total = len(gateway_results)
            failure_rate = (failed / total * 100) if total > 0 else 0

            if failure_rate > 5:
                recs.append(
                    f"⚠️ Gateway unreachable in {failure_rate:.1f}% of checks. "
                    "This indicates WiFi connectivity issues. Review WiFi configuration."
                )

            # Check packet loss
            avg_packet_loss = (
                sum(r.packet_loss for r in gateway_results) / len(gateway_results)
            )
            if avg_packet_loss > 5:
                recs.append(
                    f"⚠️ Average packet loss to gateway is {avg_packet_loss:.1f}%. "
                    "This may indicate WiFi interference or signal quality issues."
                )

            # Check latency
            latencies = [r.latency_ms for r in gateway_results if r.latency_ms]
            if latencies:
                avg_latency = sum(latencies) / len(latencies)
                if avg_latency > 50:
                    recs.append(
                        f"⚠️ High latency to gateway (average {avg_latency:.1f} ms). "
                        "Check for network congestion or WiFi interference."
                    )

        # Analyze internet
        if internet_results:
            failed = sum(1 for r in internet_results if not r.is_reachable)
            total = len(internet_results)
            failure_rate = (failed / total * 100) if total > 0 else 0

            if failure_rate > 5:
                # Check if gateway was also down
                gateway_issues = gateway_results and (
                    sum(1 for r in gateway_results if not r.is_reachable) / len(gateway_results) > 0.05
                )

                if not gateway_issues:
                    recs.append(
                        f"⚠️ Internet connectivity issues detected ({failure_rate:.1f}% failure rate) "
                        "while gateway is reachable. This indicates ISP or router issues."
                    )

        return recs

    def _analyze_time_patterns(
        self, start_time: datetime, end_time: datetime
    ) -> List[str]:
        """Analyze time-based patterns in incidents"""
        recs = []

        incidents = self.db.get_incidents(start_time=start_time, end_time=end_time)

        if not incidents:
            return recs

        # Analyze by hour
        hourly_incidents = defaultdict(int)
        for incident in incidents:
            hourly_incidents[incident.start_time.hour] += 1

        # Find problematic hours (more than average + 1 std dev)
        if len(hourly_incidents) > 3:
            import statistics

            counts = list(hourly_incidents.values())
            avg = statistics.mean(counts)
            stdev = statistics.stdev(counts) if len(counts) > 1 else 0

            problematic_hours = [
                hour
                for hour, count in hourly_incidents.items()
                if count > avg + stdev
            ]

            if problematic_hours:
                hours_str = ", ".join(f"{h:02d}:00-{h+1:02d}:00" for h in sorted(problematic_hours))
                recs.append(
                    f"⚠️ Most incidents occur during: {hours_str}. "
                    "Investigate what activities happen during these times (e.g., backups, heavy usage, interference)."
                )

        # Check for DHCP issues (IP changes)
        wifi_metrics = self.db.get_wifi_metrics(start_time, end_time)
        ip_changes = 0
        last_ip = None

        for m in wifi_metrics:
            if m.ip_address and m.is_connected:
                if last_ip and last_ip != m.ip_address:
                    ip_changes += 1
                last_ip = m.ip_address

        if ip_changes > 3:
            recs.append(
                f"⚠️ IP address changed {ip_changes} times during monitoring. "
                "Consider using a static IP address or fixing DHCP configuration to prevent connection interruptions."
            )

        return recs
