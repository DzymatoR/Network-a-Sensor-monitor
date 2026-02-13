#!/usr/bin/env python3
"""
Generate HTML report from existing database
"""

import sys
import click
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from src.models import init_db
from src.report_generator import ReportGenerator
from src.utils import load_config, parse_duration


@click.command()
@click.option(
    "--config",
    "-c",
    default="config.yml",
    type=click.Path(exists=True),
    help="Path to configuration file",
)
@click.option(
    "--db",
    type=click.Path(exists=True),
    help="Path to SQLite database (overrides config)",
)
@click.option(
    "--output",
    "-o",
    help="Output HTML file path (default: reports/report_TIMESTAMP.html)",
)
@click.option(
    "--start",
    help='Start time (ISO format: "2024-01-01 00:00:00" or relative: "24h ago")',
)
@click.option(
    "--end",
    help='End time (ISO format: "2024-01-01 23:59:59" or "now")',
)
@click.option(
    "--period",
    help='Time period to analyze (e.g., "24h", "7d"). Default: last 24 hours',
)
def main(config, db, output, start, end, period):
    """
    Generate HTML report from monitoring database.

    Examples:

      # Generate report for last 24 hours
      python generate_report.py

      # Generate report for last 7 days
      python generate_report.py --period 7d

      # Generate report for specific time range
      python generate_report.py --start "2024-01-01 00:00:00" --end "2024-01-07 23:59:59"

      # Use custom database and output
      python generate_report.py --db /path/to/monitor.db --output /path/to/report.html
    """
    try:
        # Load config
        config_data = load_config(config)

        # Determine database path
        if db:
            db_path = db
        else:
            db_path = config_data["database"]["path"]

        if not Path(db_path).exists():
            click.echo(f"Error: Database not found: {db_path}", err=True)
            sys.exit(1)

        # Initialize database
        database = init_db(db_path)

        # Determine time range
        if start and end:
            # Parse explicit time range
            start_time = (
                datetime.fromisoformat(start)
                if start != "now"
                else datetime.utcnow()
            )
            end_time = (
                datetime.fromisoformat(end) if end != "now" else datetime.utcnow()
            )
        elif period:
            # Use period
            duration = parse_duration(period)
            end_time = datetime.utcnow()
            start_time = end_time - duration
        else:
            # Default: last 24 hours
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=24)

        # Determine output path
        if output:
            output_path = Path(output)
        else:
            report_dir = Path(config_data["report"]["output_dir"])
            report_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = report_dir / f"report_{timestamp}.html"

        # Generate report
        click.echo(f"Generating report for {start_time} to {end_time}...")

        timezone = config_data["report"].get("timezone", "UTC")
        generator = ReportGenerator(database, timezone)

        generator.generate_report(str(output_path), start_time, end_time, config_data)

        click.echo(f"✓ Report generated: {output_path}")

        database.close()

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
