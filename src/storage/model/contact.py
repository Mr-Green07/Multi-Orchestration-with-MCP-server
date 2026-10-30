from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from src.storage.database import Base

class Contact(Base):
    """
    Contact ORM to store people the user might text, call, or email.
    """
    __tablename__ = 'contacts'
    
    id = Column(Integer, primary_key=True, index=True)
    
    name = Column(String, nullable=False, index=True)
    phone_number = Column(String, nullable=True)
    email = Column(String, nullable=True)
    
    # E.g. "wife", "boss" so NLU can say "Call my wife"
    relationship_alias = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
