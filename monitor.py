#!/usr/bin/env python3
"""
Network & Sensor Stability Monitor - Main CLI
"""

import sys
import click
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.monitor import NetworkMonitorApp, setup_logging
from src.utils import parse_duration


@click.command()
@click.option(
    "--config",
    "-c",
    default="config.yml",
    type=click.Path(exists=True),
    help="Path to configuration file (default: config.yml)",
)
@click.option(
    "--duration",
    "-d",
    default=None,
    help='Monitoring duration (e.g., "1h", "30m", "1d", "continuous"). Overrides config file.',
)
@click.option(
    "--report-only",
    is_flag=True,
    help="Generate report from existing database without running monitoring",
)
def main(config, duration, report_only):
    """
    Network & Sensor Stability Monitor for Raspberry Pi

    Monitor WiFi connection stability and IoT sensor availability.
    Generate detailed HTML reports with diagnostics and recommendations.

    Examples:

      # Run with default config for 24 hours
      python monitor.py --duration 24h

      # Run continuously
      python monitor.py --duration continuous

      # Use custom config
      python monitor.py --config /path/to/config.yml

      # Generate report only from existing data
      python monitor.py --report-only
    """
    try:
        from src.utils import load_config

        # Load configuration
        config_data = load_config(config)

        # Setup logging
        setup_logging(config_data)

        if report_only:
            # Generate report from existing data
            from datetime import datetime, timedelta
            from src.models import init_db
            from src.report_generator import ReportGenerator

            db_path = config_data["database"]["path"]
            db = init_db(db_path)

            # Generate report for last 24 hours by default
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=24)

            report_dir = Path(config_data["report"]["output_dir"])
            report_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = report_dir / f"report_{timestamp}.html"

            timezone = config_data["report"].get("timezone", "UTC")
            generator = ReportGenerator(db, timezone)

            click.echo("Generating report from existing data...")
            generator.generate_report(str(output_path), start_time, end_time, config_data)
            click.echo(f"Report generated: {output_path}")

            db.close()
            return

        # Determine monitoring duration
        if duration:
            # CLI argument overrides config
            duration_td = parse_duration(duration)
        else:
            # Use config file
            duration_str = config_data["monitoring"].get("duration", "24h")
            duration_td = parse_duration(duration_str)

        # Start monitoring
        app = NetworkMonitorApp(config)

        if duration_td:
            click.echo(f"Starting monitoring for {duration}...")
        else:
            click.echo("Starting continuous monitoring (Ctrl+C to stop)...")

        app.start(duration_td)

    except KeyboardInterrupt:
        click.echo("\nMonitoring interrupted by user")
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
