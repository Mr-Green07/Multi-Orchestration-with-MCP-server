from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any

class IntentType(str, Enum):
    """
    Enumeration of all supported intents across the voice assistant.
    These map exactly to the intents configured in nlu_config.json.
    """
    # Conversational
    GREETING = "greeting"
    FAREWELL = "farewell"
    HELP = "help"
    THANK_YOU = "thank_you"
    AFFIRM = "affirm"
    DENY = "deny"
    CHITCHAT = "chitchat"
    
    # Weather
    GET_WEATHER = "get_weather"
    GET_FORECAST = "get_forecast"
    
    # Media / Music
    PLAY_MUSIC = "play_music"
    STOP_MUSIC = "stop_music"
    PAUSE_MUSIC = "pause_music"
    RESUME_MUSIC = "resume_music"
    NEXT_TRACK = "next_track"
    PREVIOUS_TRACK = "previous_track"
    
    # Volume Control
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    SET_VOLUME = "set_volume"
    
    # Time / Alarms / Reminders
    SET_TIMER = "set_timer"
    CANCEL_TIMER = "cancel_timer"
    CHECK_TIMER = "check_timer"
    SET_ALARM = "set_alarm"
    CANCEL_ALARM = "cancel_alarm"
    SET_REMINDER = "set_reminder"
    GET_TIME = "get_time"
    GET_DATE = "get_date"
    
    # Smart Home / Devices
    DEVICE_ON = "device_on"
    DEVICE_OFF = "device_off"
    DEVICE_STATUS = "device_status"
    
    # Information / Web
    SEARCH_WEB = "search_web"
    TELL_JOKE = "tell_joke"
    GET_NEWS = "get_news"
    
    # Productivity
    TAKE_NOTE = "take_note"
    READ_NOTES = "read_notes"
    
    # System
    SYSTEM_STATUS = "system_status"
    SYSTEM_SHUTDOWN = "system_shutdown"
    SYSTEM_RESTART = "system_restart"
    
    # Fallback when classification fails
    UNKNOWN = "unknown"


@dataclass
class Intent:
    """
    Represents a parsed user intent along with extracted entities.
    This object is produced by the NLU engine and passed to the task executor or LLM.
    """
    type: IntentType
    confidence: float
    raw_text: str
    entities: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_reliable(self) -> bool:
        """Helper to quickly check if this intent was detected with high confidence."""
        return self.type != IntentType.UNKNOWN and self.confidence > 0.45

    def get_entity(self, key: str, default: Any = None) -> Any:
        """Safely retrieve an entity value if it exists."""
        return self.entities.get(key, default)