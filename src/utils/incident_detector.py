"""Incident detection and correlation analysis"""

import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


class IncidentDetector:
    """Detect and classify network/sensor incidents with correlation analysis"""

    def __init__(self, db):
        self.db = db
        self.active_incidents: Dict[str, int] = {}  # key -> incident_id

    def check_wifi_status(
        self, wifi_data: Dict[str, Any], rssi_critical: int = -80
    ) -> Optional[Dict[str, Any]]:
        """
        Check WiFi status and detect incidents.

        Args:
            wifi_data: WiFi metrics from WiFiMonitor
            rssi_critical: RSSI threshold for critical incidents

        Returns:
            Incident data if detected, None otherwise
        """
        incident = None

        if not wifi_data.get("is_connected"):
            # WiFi disconnected
            incident = {
                "incident_type": "wifi_outage",
                "severity": "critical",
                "description": f"WiFi interface {wifi_data['interface']} disconnected",
                "affected_targets": [wifi_data["interface"]],
            }

        elif wifi_data.get("rssi") and wifi_data["rssi"] < rssi_critical:
            # WiFi signal degraded
            incident = {
                "incident_type": "wifi_degradation",
                "severity": "warning",
                "description": f"WiFi signal weak: {wifi_data['rssi']} dBm",
                "affected_targets": [wifi_data["interface"]],
            }

        return incident

    def check_network_connectivity(
        self, gateway_result: Dict[str, Any], internet_results: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Check network connectivity and detect internet outages.

        Args:
            gateway_result: Ping result for gateway
            internet_results: Ping results for internet targets

        Returns:
            Incident data if detected, None otherwise
        """
        gateway_reachable = gateway_result.get("is_reachable", False)
        internet_reachable = any(r.get("is_reachable", False) for r in internet_results)

        if not gateway_reachable:
            # Gateway unreachable - likely WiFi or local network issue
            return {
                "incident_type": "wifi_outage",
                "severity": "critical",
                "description": f"Gateway {gateway_result['target']} unreachable",
                "affected_targets": [gateway_result["target"]],
            }

        elif gateway_reachable and not internet_reachable:
            # Gateway ok but internet down - ISP or router issue
            targets = [r["target"] for r in internet_results]
            return {
                "incident_type": "internet_outage",
                "severity": "warning",
                "description": "Internet connectivity lost (gateway reachable)",
                "affected_targets": targets,
            }

        # Check for high packet loss on gateway
        packet_loss = gateway_result.get("packet_loss", 0)
        if packet_loss > 20:
            return {
                "incident_type": "wifi_degradation",
                "severity": "warning",
                "description": f"High packet loss to gateway: {packet_loss}%",
                "affected_targets": [gateway_result["target"]],
            }

        return None

    def check_sensor_status(
        self, sensor_check: Dict[str, Any], wifi_ok: bool, gateway_ok: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Check sensor status with correlation to WiFi/gateway.

        Args:
            sensor_check: Sensor check result
            wifi_ok: Whether WiFi is currently working
            gateway_ok: Whether gateway is reachable

        Returns:
            Incident data if detected, None otherwise
        """
        if sensor_check.get("is_available"):
            return None  # Sensor is ok

        sensor_name = sensor_check.get("sensor_name", "Unknown")
        sensor_ip = sensor_check.get("sensor_ip", "Unknown")

        # Determine probable cause based on correlation
        if not wifi_ok or not gateway_ok:
            probable_cause = "WiFi/network connectivity issue (correlated with WiFi/gateway outage)"
            severity = "info"  # Not sensor's fault
        else:
            probable_cause = "Sensor-specific issue (WiFi and gateway are operational)"
            severity = "warning"  # Sensor problem

        return {
            "incident_type": "sensor_outage",
            "severity": severity,
            "description": f"Sensor '{sensor_name}' ({sensor_ip}) unavailable",
            "affected_targets": [sensor_name],
            "probable_cause": probable_cause,
        }

    def process_incident(self, incident_data: Dict[str, Any]) -> int:
        """
        Process an incident: create new or update existing.

        Args:
            incident_data: Incident information

        Returns:
            Incident ID
        """
        incident_key = f"{incident_data['incident_type']}:{json.dumps(sorted(incident_data['affected_targets']))}"

        if incident_key in self.active_incidents:
            # Incident is ongoing, update it
            incident_id = self.active_incidents[incident_key]
            logger.debug(f"Incident {incident_id} still active: {incident_data['description']}")
            return incident_id
        else:
            # New incident
            incident = self.db.add_incident(
                start_time=datetime.utcnow(),
                incident_type=incident_data["incident_type"],
                severity=incident_data["severity"],
                affected_targets=json.dumps(incident_data["affected_targets"]),
                description=incident_data["description"],
                probable_cause=incident_data.get("probable_cause"),
                is_resolved=False,
            )
            self.active_incidents[incident_key] = incident.id
            logger.warning(f"New incident detected: {incident_data['description']}")
            return incident.id

    def resolve_incident(self, incident_key: str):
        """
        Resolve an active incident.

        Args:
            incident_key: Unique key for the incident
        """
        if incident_key in self.active_incidents:
            incident_id = self.active_incidents[incident_key]

            end_time = datetime.utcnow()
            # Get incident from DB to calculate duration
            incidents = self.db.get_active_incidents()
            incident = next((i for i in incidents if i.id == incident_id), None)

            if incident:
                duration = (end_time - incident.start_time).total_seconds()
                self.db.update_incident(
                    incident_id,
                    end_time=end_time,
                    duration_seconds=int(duration),
                    is_resolved=True,
                )
                logger.info(
                    f"Incident {incident_id} resolved after {duration:.0f} seconds"
                )
            else:
                # Incident not found in DB (may have been cleaned up), just resolve
                self.db.update_incident(
                    incident_id,
                    end_time=end_time,
                    is_resolved=True,
                )

            del self.active_incidents[incident_key]

    def check_and_resolve_incidents(
        self, current_states: Dict[str, bool]
    ):
        """
        Check current states and resolve incidents that are no longer active.

        Args:
            current_states: Dict of incident_key -> is_still_active
        """
        to_resolve = []
        for incident_key in list(self.active_incidents.keys()):
            if incident_key not in current_states or not current_states[incident_key]:
                to_resolve.append(incident_key)

        for incident_key in to_resolve:
            self.resolve_incident(incident_key)

    def analyze_incident_patterns(
        self, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """
        Analyze incident patterns over a time period.

        Args:
            start_time: Analysis start time
            end_time: Analysis end time

        Returns:
            Dict with analysis results
        """
        incidents = self.db.get_incidents(start_time=start_time, end_time=end_time)

        if not incidents:
            return {
                "total_incidents": 0,
                "by_type": {},
                "by_severity": {},
                "avg_duration_seconds": 0,
                "total_downtime_seconds": 0,
                "most_affected_target": None,
            }

        # Analyze by type
        by_type = defaultdict(int)
        by_severity = defaultdict(int)
        durations = []
        affected_targets = defaultdict(int)

        for incident in incidents:
            by_type[incident.incident_type] += 1
            by_severity[incident.severity] += 1

            if incident.duration_seconds:
                durations.append(incident.duration_seconds)

            # Count affected targets
            try:
                targets = json.loads(incident.affected_targets)
                for target in targets:
                    affected_targets[target] += 1
            except (json.JSONDecodeError, TypeError):
                pass

        avg_duration = sum(durations) / len(durations) if durations else 0
        total_downtime = sum(durations)

        most_affected = (
            max(affected_targets.items(), key=lambda x: x[1])[0]
            if affected_targets
            else None
        )

        return {
            "total_incidents": len(incidents),
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
            "avg_duration_seconds": avg_duration,
            "total_downtime_seconds": total_downtime,
            "most_affected_target": most_affected,
            "mtbf_seconds": (
                (end_time - start_time).total_seconds() / len(incidents)
                if incidents
                else 0
            ),
        }

    def get_problematic_periods(
        self, start_time: datetime, end_time: datetime
    ) -> Dict[int, int]:
        """
        Find the most problematic hours of the day.

        Returns:
            Dict mapping hour (0-23) to incident count
        """
        incidents = self.db.get_incidents(start_time=start_time, end_time=end_time)

        hours = defaultdict(int)
        for incident in incidents:
            hour = incident.start_time.hour
            hours[hour] += 1

        return dict(hours)
