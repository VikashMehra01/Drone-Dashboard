from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class DensityRecord(Base):
    __tablename__ = "density_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drone_id = Column(String, ForeignKey("drones.id"), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    person_count = Column(Integer, default=0)
    density_level = Column(Float, default=0.0)  # 0.0 - 1.0
    timestamp = Column(DateTime, default=datetime.utcnow)
