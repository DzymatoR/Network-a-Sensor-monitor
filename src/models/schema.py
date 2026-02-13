"""SQLAlchemy database schema"""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class WiFiMetric(Base):
    """WiFi signal and connection metrics"""

    __tablename__ = "wifi_metrics"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    interface = Column(String(50))
    ssid = Column(String(100))
    rssi = Column(Integer)  # Signal strength in dBm
    link_quality = Column(Float)  # 0-100%
    frequency = Column(Float)  # GHz
    channel = Column(Integer)
    is_connected = Column(Boolean, default=True)
    ip_address = Column(String(45))  # IPv4 or IPv6


class PingResult(Base):
    """Ping test results for gateway and internet targets"""

    __tablename__ = "ping_results"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    target = Column(String(100), index=True)  # IP or hostname
    target_type = Column(String(20))  # 'gateway', 'internet', 'dns'
    is_reachable = Column(Boolean)
    latency_ms = Column(Float, nullable=True)  # Round-trip time
    packet_loss = Column(Float, default=0.0)  # Percentage
    ttl = Column(Integer, nullable=True)


class SensorCheck(Base):
    """Sensor availability and health checks"""

    __tablename__ = "sensor_checks"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    sensor_name = Column(String(200), index=True)
    sensor_ip = Column(String(45))
    check_type = Column(String(20))  # 'ping', 'mqtt', 'http'
    is_available = Column(Boolean)
    latency_ms = Column(Float, nullable=True)
    status_code = Column(Integer, nullable=True)  # HTTP status or MQTT connack
    error_message = Column(Text, nullable=True)


class Incident(Base):
    """Detected network/sensor incidents"""

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    start_time = Column(DateTime, index=True)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    incident_type = Column(String(50), index=True)
    # Types: 'wifi_outage', 'wifi_degradation', 'internet_outage',
    #        'sensor_outage', 'full_outage'
    severity = Column(String(20))  # 'critical', 'warning', 'info'
    affected_targets = Column(Text)  # JSON list of affected IPs/names
    description = Column(Text)
    probable_cause = Column(Text, nullable=True)
    is_resolved = Column(Boolean, default=False)


def create_tables(engine):
    """Create all tables in the database"""
    Base.metadata.create_all(engine)


def get_session(db_path: str):
    """Create a database session"""
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    create_tables(engine)
    Session = sessionmaker(bind=engine)
    return Session()
