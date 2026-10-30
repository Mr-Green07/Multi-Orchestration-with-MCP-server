from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from src.storage.database import Base

class User(Base):
    """
    User ORM for storing preferences, name, and language settings.
    """
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, index=True)
    
    # e.g., "John", what the assistant calls the user
    name = Column(String, nullable=False)
    
    # e.g., "en-US"
    language_code = Column(String, default="en-US", nullable=False)
    
    # Standard persona or custom voice preference
    voice_preference = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
