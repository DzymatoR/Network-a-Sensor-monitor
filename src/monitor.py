"""Main monitoring application"""

import logging
import signal
import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from .models import Database, init_db
from .monitors import WiFiMonitor, NetworkMonitor, SensorMonitor
from .utils import load_config, parse_duration, IncidentDetector
from .report_generator import ReportGenerator

logger = logging.getLogger(__name__)
console = Console()


class NetworkMonitorApp:
    """Main monitoring application"""

    def __init__(self, config_path: str):
        self.config = load_config(config_path)
        self.running = False
        self.start_time = None
        self.end_time = None

        # Initialize database
        db_path = self.config["database"]["path"]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = init_db(db_path)

        # Initialize monitors
        self.wifi_monitor = WiFiMonitor(self.config["wifi"]["interface"])
        self.network_monitor = NetworkMonitor(self.config["gateway"].get("timeout", 2))
        self.sensor_monitor = SensorMonitor()

        # Initialize incident detector
        self.incident_detector = IncidentDetector(self.db)

        # Statistics
        self.stats = {
            "wifi_checks": 0,
            "gateway_pings": 0,
            "internet_pings": 0,
            "sensor_checks": 0,
            "incidents": 0,
        }

        # Current state for live display
        self.current_state = {
            "wifi": {},
            "gateway": {},
            "sensors": {},
            "last_update": None,
        }

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        console.print("\n[yellow]Shutting down gracefully...[/yellow]")
        self.stop()

    def start(self, duration: Optional[timedelta] = None):
        """
        Start monitoring.

        Args:
            duration: How long to monitor (None = continuous)
        """
        self.running = True
        self.start_time = datetime.utcnow()
        self.end_time = self.start_time + duration if duration else None

        console.print("[bold green]Starting Network & Sensor Monitor[/bold green]")
        console.print(f"Start time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        if self.end_time:
            console.print(f"End time: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            console.print("Duration: Continuous")
        console.print()

        # Start monitoring threads
        threads = []

        # WiFi monitoring thread
        wifi_thread = threading.Thread(
            target=self._monitor_wifi, daemon=True, name="WiFi-Monitor"
        )
        threads.append(wifi_thread)
        wifi_thread.start()

        # Network monitoring thread
        network_thread = threading.Thread(
            target=self._monitor_network, daemon=True, name="Network-Monitor"
        )
        threads.append(network_thread)
        network_thread.start()

        # Sensor monitoring threads
        for sensor_config in self.config.get("sensors", []):
            sensor_thread = threading.Thread(
                target=self._monitor_sensor,
                args=(sensor_config,),
                daemon=True,
                name=f"Sensor-{sensor_config['name']}",
            )
            threads.append(sensor_thread)
            sensor_thread.start()

        # Report generation thread (if interval specified)
        report_interval_str = self.config["monitoring"].get("report_interval")
        if report_interval_str:
            report_interval = parse_duration(report_interval_str)
            if report_interval:
                report_thread = threading.Thread(
                    target=self._periodic_report_generator,
                    args=(report_interval,),
                    daemon=True,
                    name="Report-Generator",
                )
                threads.append(report_thread)
                report_thread.start()

        # Live display
        try:
            with Live(self._generate_display(), refresh_per_second=1, console=console) as live:
                while self.running:
                    # Check if duration expired
                    if self.end_time and datetime.utcnow() >= self.end_time:
                        console.print("\n[green]Monitoring duration completed[/green]")
                        self.stop()
                        break

                    # Update display
                    live.update(self._generate_display())
                    time.sleep(1)

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user[/yellow]")
            self.stop()

        # Wait for threads to finish
        for thread in threads:
            thread.join(timeout=5)

        # Generate final report
        self._generate_final_report()

        console.print("[bold green]Monitoring stopped[/bold green]")

    def stop(self):
        """Stop monitoring"""
        self.running = False

        # Resolve any active incidents
        for incident_key in list(self.incident_detector.active_incidents.keys()):
            self.incident_detector.resolve_incident(incident_key)

    def _monitor_wifi(self):
        """WiFi monitoring thread"""
        interval = self.config["wifi"].get("check_interval", 10)
        rssi_critical = self.config["wifi"].get("rssi_critical_threshold", -80)
        last_cleanup = datetime.utcnow()

        while self.running:
            try:
                # Get WiFi status
                wifi_data = self.wifi_monitor.get_wifi_status()

                # Save to database
                self.db.add_wifi_metric(**wifi_data)

                # Update current state
                self.current_state["wifi"] = wifi_data
                self.current_state["last_update"] = datetime.utcnow()
                self.stats["wifi_checks"] += 1

                # Check for incidents
                incident = self.incident_detector.check_wifi_status(
                    wifi_data, rssi_critical
                )
                if incident:
                    self.incident_detector.process_incident(incident)
                else:
                    # WiFi is ok, resolve any active WiFi incidents
                    import json as _json
                    for key in list(self.incident_detector.active_incidents.keys()):
                        if key.startswith("wifi_outage:") or key.startswith("wifi_degradation:"):
                            self.incident_detector.resolve_incident(key)

                self.stats["incidents"] = len(self.incident_detector.active_incidents)

                # Periodic data cleanup (every 6 hours)
                if (datetime.utcnow() - last_cleanup).total_seconds() > 21600:
                    retention_days = self.config["monitoring"].get("data_retention_days", 7)
                    self.db.cleanup_old_data(retention_days)
                    last_cleanup = datetime.utcnow()

            except Exception as e:
                logger.error(f"Error in WiFi monitoring: {e}", exc_info=True)

            time.sleep(interval)

    def _monitor_network(self):
        """Network connectivity monitoring thread"""
        gateway_ip = self.config["gateway"]["ip"]
        gateway_interval = self.config["gateway"].get("ping_interval", 5)
        internet_targets = self.config.get("internet_targets", [])

        while self.running:
            try:
                # Ping gateway
                gateway_result = self.network_monitor.ping(
                    gateway_ip, count=1, target_type="gateway"
                )
                self.db.add_ping_result(**gateway_result)
                self.current_state["gateway"] = gateway_result
                self.stats["gateway_pings"] += 1

                # Ping internet targets
                internet_results = []
                for target in internet_targets:
                    result = self.network_monitor.ping(
                        target, count=1, target_type="internet"
                    )
                    self.db.add_ping_result(**result)
                    internet_results.append(result)
                    self.stats["internet_pings"] += 1

                # Check for network incidents
                incident = self.incident_detector.check_network_connectivity(
                    gateway_result, internet_results
                )
                if incident:
                    self.incident_detector.process_incident(incident)
                else:
                    # Network is ok, resolve related incidents
                    for key in list(self.incident_detector.active_incidents.keys()):
                        if key.startswith("internet_outage:"):
                            self.incident_detector.resolve_incident(key)

                self.stats["incidents"] = len(self.incident_detector.active_incidents)

            except Exception as e:
                logger.error(f"Error in network monitoring: {e}", exc_info=True)

            time.sleep(gateway_interval)

    def _monitor_sensor(self, sensor_config: dict):
        """Sensor monitoring thread"""
        name = sensor_config["name"]
        ip = sensor_config["ip"]
        sensor_type = sensor_config["type"]
        interval = sensor_config.get("interval", 30)
        timeout = sensor_config.get("timeout", 5)

        while self.running:
            try:
                # Perform check based on type
                if sensor_type == "ping":
                    result = self.sensor_monitor.check_ping(ip, timeout)
                elif sensor_type == "mqtt":
                    port = sensor_config.get("port", 1883)
                    username = sensor_config.get("username")
                    password = sensor_config.get("password")
                    result = self.sensor_monitor.check_mqtt(
                        ip, port, timeout, username, password
                    )
                elif sensor_type == "http":
                    port = sensor_config.get("port", 80)
                    path = sensor_config.get("path", "/")
                    https = sensor_config.get("https", False)
                    result = self.sensor_monitor.check_http(
                        ip, port, path, timeout, https
                    )
                else:
                    logger.error(f"Unknown sensor type: {sensor_type}")
                    return

                # Save to database
                self.db.add_sensor_check(
                    sensor_name=name,
                    sensor_ip=ip,
                    check_type=sensor_type,
                    **result,
                )

                # Update current state
                if "sensors" not in self.current_state:
                    self.current_state["sensors"] = {}
                self.current_state["sensors"][name] = result
                self.stats["sensor_checks"] += 1

                # Check for sensor incidents (correlate with WiFi/gateway)
                wifi_ok = self.current_state.get("wifi", {}).get("is_connected", False)
                gateway_ok = self.current_state.get("gateway", {}).get(
                    "is_reachable", False
                )

                incident = self.incident_detector.check_sensor_status(
                    {"sensor_name": name, "sensor_ip": ip, **result},
                    wifi_ok,
                    gateway_ok,
                )
                if incident:
                    self.incident_detector.process_incident(incident)
                else:
                    # Sensor is ok, resolve any active sensor incidents for this sensor
                    import json as _json
                    sensor_key = f"sensor_outage:{_json.dumps([name])}"
                    if sensor_key in self.incident_detector.active_incidents:
                        self.incident_detector.resolve_incident(sensor_key)

                self.stats["incidents"] = len(self.incident_detector.active_incidents)

            except Exception as e:
                logger.error(f"Error monitoring sensor {name}: {e}", exc_info=True)

            time.sleep(interval)

    def _periodic_report_generator(self, interval: timedelta):
        """Periodically generate reports"""
        while self.running:
            time.sleep(interval.total_seconds())

            if not self.running:
                break

            try:
                self._generate_report(intermediate=True)
            except Exception as e:
                logger.error(f"Error generating periodic report: {e}", exc_info=True)

    def _generate_report(self, intermediate: bool = False):
        """Generate HTML report"""
        report_dir = Path(self.config["report"]["output_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_{'intermediate_' if intermediate else ''}{timestamp}.html"
        output_path = report_dir / filename

        timezone = self.config["report"].get("timezone", "UTC")
        generator = ReportGenerator(self.db, timezone)

        generator.generate_report(
            str(output_path), self.start_time, datetime.utcnow(), self.config
        )

        logger.info(f"Report generated: {output_path}")

    def _generate_final_report(self):
        """Generate final report on shutdown"""
        try:
            console.print("\n[cyan]Generating final report...[/cyan]")
            self._generate_report(intermediate=False)
            console.print("[green]Final report generated[/green]")
        except Exception as e:
            logger.error(f"Error generating final report: {e}", exc_info=True)
            console.print(f"[red]Error generating report: {e}[/red]")

    def _generate_display(self) -> Layout:
        """Generate live display layout"""
        layout = Layout()

        # Header
        header = Panel(
            Text("Network & Sensor Stability Monitor", style="bold green", justify="center"),
            style="bold green",
        )

        # Stats table
        stats_table = Table(show_header=False, box=None)
        stats_table.add_column("Stat", style="cyan")
        stats_table.add_column("Value", style="white")

        elapsed = (
            datetime.utcnow() - self.start_time if self.start_time else timedelta(0)
        )
        remaining = (
            self.end_time - datetime.utcnow()
            if self.end_time
            else None
        )

        stats_table.add_row("Elapsed", str(elapsed).split(".")[0])
        if remaining:
            stats_table.add_row("Remaining", str(remaining).split(".")[0])
        stats_table.add_row("WiFi Checks", str(self.stats["wifi_checks"]))
        stats_table.add_row("Gateway Pings", str(self.stats["gateway_pings"]))
        stats_table.add_row("Sensor Checks", str(self.stats["sensor_checks"]))
        stats_table.add_row("Active Incidents", str(self.stats["incidents"]))

        # WiFi status
        wifi = self.current_state.get("wifi", {})
        wifi_status = "✓ Connected" if wifi.get("is_connected") else "✗ Disconnected"
        wifi_color = "green" if wifi.get("is_connected") else "red"
        rssi = wifi.get("rssi", "N/A")
        ssid = wifi.get("ssid", "N/A")

        wifi_text = f"[{wifi_color}]{wifi_status}[/{wifi_color}]\n"
        wifi_text += f"SSID: {ssid}\n"
        wifi_text += f"RSSI: {rssi} dBm\n"
        wifi_text += f"Quality: {self.wifi_monitor.get_signal_quality_rating(rssi) if isinstance(rssi, int) else 'N/A'}"

        wifi_panel = Panel(wifi_text, title="WiFi Status", border_style="cyan")

        # Gateway status
        gateway = self.current_state.get("gateway", {})
        gateway_status = "✓ Reachable" if gateway.get("is_reachable") else "✗ Unreachable"
        gateway_color = "green" if gateway.get("is_reachable") else "red"
        latency = gateway.get("latency_ms", "N/A")

        gateway_text = f"[{gateway_color}]{gateway_status}[/{gateway_color}]\n"
        gateway_text += f"Latency: {latency} ms\n" if isinstance(latency, (int, float)) else "Latency: N/A\n"
        gateway_text += f"Packet Loss: {gateway.get('packet_loss', 0):.1f}%"

        gateway_panel = Panel(gateway_text, title="Gateway", border_style="cyan")

        # Sensors status
        sensors = self.current_state.get("sensors", {})
        sensor_table = Table(show_header=True, box=None)
        sensor_table.add_column("Sensor", style="cyan")
        sensor_table.add_column("Status", style="white")
        sensor_table.add_column("Latency", style="white")

        for name, data in sensors.items():
            status = "✓" if data.get("is_available") else "✗"
            status_color = "green" if data.get("is_available") else "red"
            latency_val = data.get("latency_ms", "N/A")
            latency_str = f"{latency_val:.1f} ms" if isinstance(latency_val, (int, float)) else "N/A"

            sensor_table.add_row(
                name,
                f"[{status_color}]{status}[/{status_color}]",
                latency_str,
            )

        sensors_panel = Panel(sensor_table, title="Sensors", border_style="cyan")

        # Combine layout
        layout.split_column(
            Layout(header, size=3),
            Layout(stats_table, size=8),
            Layout(name="status").split_row(wifi_panel, gateway_panel),
            Layout(sensors_panel),
        )

        return layout


def setup_logging(config: dict):
    """Setup logging configuration"""
    log_config = config.get("logging", {})
    log_file = log_config.get("file", "/app/logs/monitor.log")
    log_level = log_config.get("level", "INFO")

    # Create log directory
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    # Configure logging
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(
        log_file,
        maxBytes=log_config.get("max_bytes", 10485760),
        backupCount=log_config.get("backup_count", 5),
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    )

    logging.basicConfig(
        level=getattr(logging, log_level),
        handlers=[handler],
    )
