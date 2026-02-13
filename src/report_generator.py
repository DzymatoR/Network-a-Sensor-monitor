"""HTML report generator with Plotly charts"""

import logging
import json
from typing import Dict, Any, List
from datetime import datetime, timedelta
from pathlib import Path
import pytz

from jinja2 import Environment, FileSystemLoader

from .models.database import Database
from .utils.recommendations import RecommendationEngine


class _DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that serializes datetime objects to ISO strings"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        return super().default(obj)

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate HTML reports with Plotly visualizations"""

    def __init__(self, db: Database, timezone: str = "UTC"):
        self.db = db
        self.timezone = pytz.timezone(timezone)
        self.recommendation_engine = RecommendationEngine(db)

    def generate_report(
        self,
        output_path: str,
        start_time: datetime,
        end_time: datetime,
        config: Dict[str, Any],
    ):
        """
        Generate complete HTML report.

        Args:
            output_path: Path to save HTML report
            start_time: Report start time
            end_time: Report end time
            config: Configuration dict
        """
        logger.info(f"Generating report for {start_time} to {end_time}")

        # Collect data
        summary_data = self._collect_summary_data(start_time, end_time, config)
        wifi_data = self._collect_wifi_data(start_time, end_time)
        network_data = self._collect_network_data(start_time, end_time, config)
        sensor_data = self._collect_sensor_data(start_time, end_time, config)
        incident_data = self._collect_incident_data(start_time, end_time)

        # Generate charts
        charts_js = self._generate_charts_javascript(
            wifi_data, network_data, sensor_data, incident_data
        )

        # Generate recommendations
        recommendations = self.recommendation_engine.generate_recommendations(
            start_time, end_time
        )

        # Render template
        template_dir = Path(__file__).parent / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("report_template.html")

        html = template.render(
            monitoring_period=self._format_period(start_time, end_time),
            generated_at=self._format_datetime(datetime.now(self.timezone)),
            **summary_data,
            sensors=sensor_data["sensor_list"],
            incidents=incident_data["incident_list"],
            incident_stats=incident_data.get("stats"),
            recommendations=recommendations,
            chart_data=charts_js,
            show_rssi_vs_packetloss=len(wifi_data.get("rssi", [])) > 10,
            show_latency_histogram=len(network_data.get("gateway_latency", [])) > 20,
        )

        # Write report
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"Report generated: {output_path}")

    def _collect_summary_data(
        self, start_time: datetime, end_time: datetime, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Collect summary statistics"""
        # WiFi uptime
        wifi_uptime = self.db.get_wifi_uptime(start_time, end_time)

        # Average RSSI
        wifi_metrics = self.db.get_wifi_metrics(start_time, end_time)
        rssi_values = [m.rssi for m in wifi_metrics if m.rssi]
        avg_rssi = sum(rssi_values) / len(rssi_values) if rssi_values else 0

        # WiFi grade
        grade, rating = self._calculate_wifi_grade(wifi_uptime["uptime_percentage"], avg_rssi)

        # Incidents
        incidents = self.db.get_incidents(start_time, end_time)
        total_downtime = sum(
            i.duration_seconds for i in incidents if i.duration_seconds
        )

        return {
            "wifi_uptime": f"{wifi_uptime['uptime_percentage']:.1f}",
            "wifi_checks": wifi_uptime["total_checks"],
            "wifi_grade": grade,
            "wifi_rating": rating,
            "avg_rssi": f"{avg_rssi:.0f}",
            "rssi_quality": self._rssi_quality(avg_rssi),
            "total_incidents": len(incidents),
            "total_downtime": self._format_duration(total_downtime),
        }

    def _collect_wifi_data(
        self, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """Collect WiFi metrics data"""
        metrics = self.db.get_wifi_metrics(start_time, end_time)

        timestamps = [self._to_local_time(m.timestamp) for m in metrics]
        rssi = [m.rssi for m in metrics]
        link_quality = [m.link_quality for m in metrics]
        is_connected = [m.is_connected for m in metrics]

        return {
            "timestamps": timestamps,
            "rssi": rssi,
            "link_quality": link_quality,
            "is_connected": is_connected,
        }

    def _collect_network_data(
        self, start_time: datetime, end_time: datetime, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Collect network ping data"""
        gateway_ip = config["gateway"]["ip"]
        internet_targets = config.get("internet_targets", [])

        # Gateway data
        gateway_results = self.db.get_ping_results(gateway_ip, start_time, end_time)

        # Internet data (combine all targets)
        internet_results = []
        for target in internet_targets:
            results = self.db.get_ping_results(target, start_time, end_time)
            internet_results.extend(results)

        return {
            "gateway_timestamps": [self._to_local_time(r.timestamp) for r in gateway_results],
            "gateway_latency": [r.latency_ms for r in gateway_results if r.latency_ms],
            "gateway_packet_loss": [r.packet_loss for r in gateway_results],
            "gateway_reachable": [r.is_reachable for r in gateway_results],
            "internet_timestamps": [self._to_local_time(r.timestamp) for r in internet_results],
            "internet_latency": [r.latency_ms for r in internet_results if r.latency_ms],
            "internet_reachable": [r.is_reachable for r in internet_results],
        }

    def _collect_sensor_data(
        self, start_time: datetime, end_time: datetime, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Collect sensor monitoring data"""
        sensors_config = config.get("sensors", [])
        sensor_list = []
        sensor_timelines = {}

        for sensor_config in sensors_config:
            name = sensor_config["name"]
            ip = sensor_config["ip"]

            stats = self.db.get_sensor_availability(name, start_time, end_time)
            checks = self.db.get_sensor_checks(name, start_time, end_time)

            availability = stats["availability_percentage"]
            avg_latency = stats["avg_latency_ms"]

            # Determine status
            if availability >= 99:
                status = "Excellent"
                status_class = "ok"
            elif availability >= 95:
                status = "Good"
                status_class = "ok"
            elif availability >= 90:
                status = "Fair"
                status_class = "warning"
            else:
                status = "Poor"
                status_class = "critical"

            sensor_list.append({
                "name": name,
                "ip": ip,
                "availability": f"{availability:.1f}",
                "avg_latency": f"{avg_latency:.1f} ms" if avg_latency else "N/A",
                "status": status,
                "status_class": status_class,
            })

            # Timeline data
            sensor_timelines[name] = {
                "timestamps": [self._to_local_time(c.timestamp) for c in checks],
                "available": [c.is_available for c in checks],
            }

        return {
            "sensor_list": sensor_list,
            "sensor_timelines": sensor_timelines,
        }

    def _collect_incident_data(
        self, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """Collect incident data"""
        incidents = self.db.get_incidents(start_time, end_time)

        incident_list = []
        for incident in incidents:
            incident_list.append({
                "start_time": self._format_datetime(self._to_local_time(incident.start_time)),
                "duration": self._format_duration(incident.duration_seconds or 0),
                "type": incident.incident_type.replace("_", " ").title(),
                "severity": incident.severity,
                "description": incident.description,
            })

        # Incident stats
        from collections import Counter

        types = Counter(i.incident_type for i in incidents)
        severities = Counter(i.severity for i in incidents)

        return {
            "incident_list": incident_list,
            "stats": {
                "by_type": dict(types),
                "by_severity": dict(severities),
            },
        }

    def _dumps(self, obj) -> str:
        """JSON serialize with datetime support"""
        return json.dumps(cls=_DateTimeEncoder, obj=obj)

    def _generate_charts_javascript(
        self,
        wifi_data: Dict,
        network_data: Dict,
        sensor_data: Dict,
        incident_data: Dict,
    ) -> str:
        """Generate JavaScript code for Plotly charts"""
        charts = []

        # WiFi RSSI chart
        if wifi_data.get("rssi"):
            traces, layout = self._create_rssi_chart(
                wifi_data["timestamps"], wifi_data["rssi"]
            )
            layout["title"] = "WiFi Signal Strength (RSSI)"
            layout["height"] = 400
            charts.append(
                f"Plotly.newPlot('wifi-rssi-chart', {self._dumps(traces)}, {self._dumps(layout)});"
            )

        # WiFi connection timeline
        if wifi_data.get("is_connected"):
            traces, layout = self._create_wifi_timeline(
                wifi_data["timestamps"], wifi_data["is_connected"]
            )
            layout["title"] = "WiFi Connection Status"
            layout["height"] = 200
            charts.append(
                f"Plotly.newPlot('wifi-timeline-chart', {self._dumps(traces)}, {self._dumps(layout)});"
            )

        # Latency comparison chart
        if network_data.get("gateway_latency"):
            traces, layout = self._create_latency_chart(network_data)
            layout["title"] = "Network Latency"
            layout["height"] = 400
            charts.append(
                f"Plotly.newPlot('latency-chart', {self._dumps(traces)}, {self._dumps(layout)});"
            )

        # Packet loss chart
        if network_data.get("gateway_packet_loss"):
            traces, layout = self._create_packet_loss_chart(network_data)
            layout["title"] = "Packet Loss"
            layout["height"] = 300
            charts.append(
                f"Plotly.newPlot('packet-loss-chart', {self._dumps(traces)}, {self._dumps(layout)});"
            )

        # Sensor timeline
        if sensor_data.get("sensor_timelines"):
            traces, layout = self._create_sensor_timeline(sensor_data["sensor_timelines"])
            layout["title"] = "Sensor Availability Timeline"
            layout["height"] = 300
            charts.append(
                f"Plotly.newPlot('sensor-timeline-chart', {self._dumps(traces)}, {self._dumps(layout)});"
            )

        # Incidents timeline
        if incident_data.get("incident_list"):
            traces, layout = self._create_incidents_timeline(incident_data)
            layout["title"] = "Incidents Timeline"
            layout["height"] = 300
            charts.append(
                f"Plotly.newPlot('incidents-timeline-chart', {self._dumps(traces)}, {self._dumps(layout)});"
            )

        return "\n".join(charts)

    def _create_rssi_chart(self, timestamps: List, rssi: List) -> tuple:
        """Create RSSI line chart with colored zones"""
        traces = [{
            "x": [self._format_datetime(t) for t in timestamps],
            "y": rssi,
            "type": "scatter",
            "mode": "lines",
            "name": "RSSI",
            "line": {"color": "#667eea"},
        }]

        shapes = [
            {"type": "rect", "xref": "paper", "yref": "y", "x0": 0, "x1": 1, "y0": -50, "y1": 0,
             "fillcolor": "green", "opacity": 0.1, "line": {"width": 0}},
            {"type": "rect", "xref": "paper", "yref": "y", "x0": 0, "x1": 1, "y0": -70, "y1": -50,
             "fillcolor": "yellow", "opacity": 0.1, "line": {"width": 0}},
            {"type": "rect", "xref": "paper", "yref": "y", "x0": 0, "x1": 1, "y0": -100, "y1": -70,
             "fillcolor": "red", "opacity": 0.1, "line": {"width": 0}},
        ]

        layout = {
            "yaxis": {"title": "RSSI (dBm)"},
            "xaxis": {"title": "Time"},
            "shapes": shapes,
        }

        return traces, layout

    def _create_wifi_timeline(self, timestamps: List, is_connected: List) -> tuple:
        """Create WiFi connection status timeline"""
        status = [1 if c else 0 for c in is_connected]

        traces = [{
            "x": [self._format_datetime(t) for t in timestamps],
            "y": status,
            "type": "scatter",
            "mode": "lines",
            "fill": "tozeroy",
            "line": {"shape": "hv", "color": "#27ae60"},
            "fillcolor": "rgba(39, 174, 96, 0.3)",
        }]

        layout = {
            "yaxis": {"tickvals": [0, 1], "ticktext": ["Disconnected", "Connected"]},
            "xaxis": {"title": "Time"},
        }

        return traces, layout

    def _create_latency_chart(self, network_data: Dict) -> tuple:
        """Create latency comparison chart"""
        traces = []

        if network_data.get("gateway_latency"):
            traces.append({
                "x": [self._format_datetime(t) for t in network_data["gateway_timestamps"]],
                "y": network_data["gateway_latency"],
                "type": "scatter",
                "mode": "lines",
                "name": "Gateway",
                "line": {"color": "#667eea"},
            })

        if network_data.get("internet_latency"):
            traces.append({
                "x": [self._format_datetime(t) for t in network_data["internet_timestamps"]],
                "y": network_data["internet_latency"],
                "type": "scatter",
                "mode": "lines",
                "name": "Internet",
                "line": {"color": "#f39c12"},
            })

        layout = {
            "yaxis": {"title": "Latency (ms)"},
            "xaxis": {"title": "Time"},
        }

        return traces, layout

    def _create_packet_loss_chart(self, network_data: Dict) -> tuple:
        """Create packet loss chart"""
        traces = [{
            "x": [self._format_datetime(t) for t in network_data["gateway_timestamps"]],
            "y": network_data["gateway_packet_loss"],
            "type": "scatter",
            "mode": "lines",
            "fill": "tozeroy",
            "line": {"color": "#e74c3c"},
            "fillcolor": "rgba(231, 76, 60, 0.3)",
        }]

        layout = {
            "yaxis": {"title": "Packet Loss (%)"},
            "xaxis": {"title": "Time"},
        }

        return traces, layout

    def _create_sensor_timeline(self, sensor_timelines: Dict) -> tuple:
        """Create sensor availability heatmap/timeline"""
        traces = []

        for name, data in sensor_timelines.items():
            status = [1 if a else 0 for a in data["available"]]

            traces.append({
                "x": [self._format_datetime(t) for t in data["timestamps"]],
                "y": [name] * len(data["timestamps"]),
                "mode": "markers",
                "marker": {
                    "color": status,
                    "colorscale": [[0, "red"], [1, "green"]],
                    "size": 8,
                },
                "name": name,
                "showlegend": False,
            })

        layout = {
            "xaxis": {"title": "Time"},
            "yaxis": {"title": "Sensor"},
        }

        return traces, layout

    def _create_incidents_timeline(self, incident_data: Dict) -> tuple:
        """Create incidents timeline chart"""
        incidents = incident_data["incident_list"]

        if not incidents:
            return [], {"xaxis": {"title": "Time"}, "yaxis": {"title": "Incident Type"}}

        traces = []
        by_type = {}
        for inc in incidents:
            typ = inc["type"]
            if typ not in by_type:
                by_type[typ] = []
            by_type[typ].append(inc)

        colors = {
            "Wifi Outage": "#e74c3c",
            "Wifi Degradation": "#f39c12",
            "Internet Outage": "#3498db",
            "Sensor Outage": "#9b59b6",
            "Full Outage": "#2c3e50",
        }

        for typ, incs in by_type.items():
            traces.append({
                "x": [i["start_time"] for i in incs],
                "y": [typ] * len(incs),
                "mode": "markers",
                "marker": {"color": colors.get(typ, "#95a5a6"), "size": 10},
                "name": typ,
            })

        layout = {
            "xaxis": {"title": "Time"},
            "yaxis": {"title": "Incident Type"},
        }

        return traces, layout

    # Helper methods
    def _to_local_time(self, dt: datetime) -> datetime:
        """Convert UTC datetime to local timezone"""
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(self.timezone)

    def _format_datetime(self, dt: datetime) -> str:
        """Format datetime for display"""
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def _format_period(self, start: datetime, end: datetime) -> str:
        """Format monitoring period"""
        return f"{self._format_datetime(self._to_local_time(start))} - {self._format_datetime(self._to_local_time(end))}"

    def _format_duration(self, seconds: int) -> str:
        """Format duration in human-readable form"""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}h {minutes}m"

    def _calculate_wifi_grade(self, uptime: float, avg_rssi: float) -> tuple:
        """Calculate WiFi grade A-F based on uptime and signal"""
        # Weighted score
        uptime_score = uptime  # 0-100
        rssi_score = max(0, min(100, (avg_rssi + 90) * 2))  # -90 to -40 dBm mapped to 0-100

        combined_score = (uptime_score * 0.7 + rssi_score * 0.3)

        if combined_score >= 95:
            return "A", "Excellent"
        elif combined_score >= 85:
            return "B", "Good"
        elif combined_score >= 75:
            return "C", "Fair"
        elif combined_score >= 65:
            return "D", "Poor"
        else:
            return "F", "Very Poor"

    def _rssi_quality(self, rssi: float) -> str:
        """Get RSSI quality description"""
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
