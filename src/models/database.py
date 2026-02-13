"""Database management and operations (thread-safe)"""

import logging
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, scoped_session

from .schema import (
    Base,
    WiFiMetric,
    PingResult,
    SensorCheck,
    Incident,
)

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe database interface for monitoring data"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)
        self._Session = scoped_session(self._session_factory)
        logger.info(f"Database initialized: {db_path}")

    def close(self):
        """Close database connections"""
        self._Session.remove()
        self._engine.dispose()

    # WiFi Metrics
    def add_wifi_metric(self, **kwargs) -> WiFiMetric:
        """Add WiFi metric to database"""
        with self._lock:
            session = self._Session()
            metric = WiFiMetric(**kwargs)
            session.add(metric)
            session.commit()
            return metric

    def get_wifi_metrics(
        self, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None
    ) -> List[WiFiMetric]:
        """Get WiFi metrics within time range"""
        session = self._Session()
        query = session.query(WiFiMetric)
        if start_time:
            query = query.filter(WiFiMetric.timestamp >= start_time)
        if end_time:
            query = query.filter(WiFiMetric.timestamp <= end_time)
        return query.order_by(WiFiMetric.timestamp).all()

    # Ping Results
    def add_ping_result(self, **kwargs) -> PingResult:
        """Add ping result to database, filtering out unknown columns"""
        valid_columns = {c.name for c in PingResult.__table__.columns}
        filtered = {k: v for k, v in kwargs.items() if k in valid_columns}
        with self._lock:
            session = self._Session()
            result = PingResult(**filtered)
            session.add(result)
            session.commit()
            return result

    def get_ping_results(
        self,
        target: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[PingResult]:
        """Get ping results within time range"""
        session = self._Session()
        query = session.query(PingResult)
        if target:
            query = query.filter(PingResult.target == target)
        if start_time:
            query = query.filter(PingResult.timestamp >= start_time)
        if end_time:
            query = query.filter(PingResult.timestamp <= end_time)
        return query.order_by(PingResult.timestamp).all()

    # Sensor Checks
    def add_sensor_check(self, **kwargs) -> SensorCheck:
        """Add sensor check to database, filtering out unknown columns"""
        valid_columns = {c.name for c in SensorCheck.__table__.columns}
        filtered = {k: v for k, v in kwargs.items() if k in valid_columns}
        with self._lock:
            session = self._Session()
            check = SensorCheck(**filtered)
            session.add(check)
            session.commit()
            return check

    def get_sensor_checks(
        self,
        sensor_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[SensorCheck]:
        """Get sensor checks within time range"""
        session = self._Session()
        query = session.query(SensorCheck)
        if sensor_name:
            query = query.filter(SensorCheck.sensor_name == sensor_name)
        if start_time:
            query = query.filter(SensorCheck.timestamp >= start_time)
        if end_time:
            query = query.filter(SensorCheck.timestamp <= end_time)
        return query.order_by(SensorCheck.timestamp).all()

    # Incidents
    def add_incident(self, **kwargs) -> Incident:
        """Add incident to database"""
        with self._lock:
            session = self._Session()
            incident = Incident(**kwargs)
            session.add(incident)
            session.commit()
            return incident

    def update_incident(self, incident_id: int, **kwargs) -> Optional[Incident]:
        """Update existing incident"""
        with self._lock:
            session = self._Session()
            incident = session.query(Incident).filter(Incident.id == incident_id).first()
            if incident:
                for key, value in kwargs.items():
                    setattr(incident, key, value)
                session.commit()
            return incident

    def get_incidents(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        incident_type: Optional[str] = None,
    ) -> List[Incident]:
        """Get incidents within time range"""
        session = self._Session()
        query = session.query(Incident)
        if start_time:
            query = query.filter(Incident.start_time >= start_time)
        if end_time:
            query = query.filter(Incident.start_time <= end_time)
        if incident_type:
            query = query.filter(Incident.incident_type == incident_type)
        return query.order_by(Incident.start_time).all()

    def get_active_incidents(self) -> List[Incident]:
        """Get all unresolved incidents"""
        session = self._Session()
        return session.query(Incident).filter(Incident.is_resolved == False).all()

    # Statistics
    def get_wifi_uptime(
        self, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """Calculate WiFi uptime percentage"""
        session = self._Session()
        total = (
            session.query(WiFiMetric)
            .filter(and_(
                WiFiMetric.timestamp >= start_time,
                WiFiMetric.timestamp <= end_time,
            ))
            .count()
        )
        connected = (
            session.query(WiFiMetric)
            .filter(and_(
                WiFiMetric.timestamp >= start_time,
                WiFiMetric.timestamp <= end_time,
                WiFiMetric.is_connected == True,
            ))
            .count()
        )
        uptime_pct = (connected / total * 100) if total > 0 else 0
        return {
            "total_checks": total,
            "connected_checks": connected,
            "uptime_percentage": uptime_pct,
        }

    def get_target_availability(
        self, target: str, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """Calculate target availability statistics"""
        session = self._Session()
        results = (
            session.query(PingResult)
            .filter(and_(
                PingResult.target == target,
                PingResult.timestamp >= start_time,
                PingResult.timestamp <= end_time,
            ))
            .all()
        )
        if not results:
            return {
                "total_checks": 0, "successful_checks": 0,
                "availability_percentage": 0,
                "avg_latency_ms": None, "avg_packet_loss": None,
            }
        successful = sum(1 for r in results if r.is_reachable)
        latencies = [r.latency_ms for r in results if r.is_reachable and r.latency_ms]
        packet_losses = [r.packet_loss for r in results]
        return {
            "total_checks": len(results),
            "successful_checks": successful,
            "availability_percentage": (successful / len(results) * 100),
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "avg_packet_loss": sum(packet_losses) / len(packet_losses),
        }

    def get_sensor_availability(
        self, sensor_name: str, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """Calculate sensor availability statistics"""
        session = self._Session()
        checks = (
            session.query(SensorCheck)
            .filter(and_(
                SensorCheck.sensor_name == sensor_name,
                SensorCheck.timestamp >= start_time,
                SensorCheck.timestamp <= end_time,
            ))
            .all()
        )
        if not checks:
            return {
                "total_checks": 0, "successful_checks": 0,
                "availability_percentage": 0, "avg_latency_ms": None,
            }
        successful = sum(1 for c in checks if c.is_available)
        latencies = [c.latency_ms for c in checks if c.is_available and c.latency_ms]
        return {
            "total_checks": len(checks),
            "successful_checks": successful,
            "availability_percentage": (successful / len(checks) * 100),
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        }

    # Data retention
    def cleanup_old_data(self, days: int = 7):
        """Remove data older than specified days"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self._lock:
            session = self._Session()
            deleted_wifi = session.query(WiFiMetric).filter(WiFiMetric.timestamp < cutoff).delete()
            deleted_ping = session.query(PingResult).filter(PingResult.timestamp < cutoff).delete()
            deleted_sensor = session.query(SensorCheck).filter(SensorCheck.timestamp < cutoff).delete()
            deleted_incidents = session.query(Incident).filter(Incident.start_time < cutoff).delete()
            session.commit()
        logger.info(
            f"Cleaned up old data: {deleted_wifi} WiFi, "
            f"{deleted_ping} ping, {deleted_sensor} sensor, "
            f"{deleted_incidents} incidents"
        )


def init_db(db_path: str) -> Database:
    """Initialize database and return Database instance"""
    return Database(db_path)
