from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from src.storage.database import Base

class Conversation(Base):
    """
    Represents a single conversational session or thread with the user.
    """
    __tablename__ = 'conversations'
    
    id = Column(Integer, primary_key=True, index=True)
    start_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # A conversation can have many messages
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """
    Represents a single back-and-forth interaction (STT -> LLM history)
    within a conversation.
    """
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey('conversations.id'), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    user_text = Column(String, nullable=False)       # Output from ASR
    intent = Column(String, nullable=False)          # Output from NLU
    response = Column(String, nullable=False)        # Read by TTS
    
    audio_path = Column(String, nullable=True)       # Path to raw audio
    processing_time_ms = Column(Float, nullable=False, default=0.0)

    conversation = relationship("Conversation", back_populates="messages")
