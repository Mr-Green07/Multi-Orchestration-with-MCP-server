from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime

from src.storage.database import Base

class Reminder(Base):
    """
    Reminder ORM to track alarms, timers, and scheduled tasks.
    """
    __tablename__ = 'reminders'
    
    id = Column(Integer, primary_key=True, index=True)
    
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    
    # When this reminder should trigger
    trigger_time = Column(DateTime, nullable=False)
    
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
