from .conversation import Conversation, Message
from .user import User
from .reminder import Reminder
from .contact import Contact

# Include Setting here if we want to migrate it into the module pattern
# (We define it in this directory or import it if left outside, 
# for now we'll define a quick Setting ORM to match the old models_definitions)

from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from src.storage.database import Base

class Setting(Base):
    __tablename__ = 'settings'
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    value = Column(String, nullable=False)
    is_encrypted = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

__all__ = [
    "Conversation",
    "Message",
    "User",
    "Reminder",
    "Contact",
    "Setting"
]
