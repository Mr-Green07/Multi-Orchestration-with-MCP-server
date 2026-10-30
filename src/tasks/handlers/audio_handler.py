from src.tasks.registry import TaskRegistry, BaseTaskHandler
from src.nlu.intent import IntentType, Intent

@TaskRegistry.register(IntentType.PLAY_MUSIC)
@TaskRegistry.register(IntentType.STOP_MUSIC)
@TaskRegistry.register(IntentType.PAUSE_MUSIC)
@TaskRegistry.register(IntentType.RESUME_MUSIC)
@TaskRegistry.register(IntentType.NEXT_TRACK)
@TaskRegistry.register(IntentType.PREVIOUS_TRACK)
class AudioHandler(BaseTaskHandler):
    """Handles music playback and media controls."""
    
    def execute(self, intent: Intent) -> dict:
        action = intent.type.value
        
        if intent.type == IntentType.PLAY_MUSIC:
            genre = intent.get_entity("genre")
            mood = intent.get_entity("mood")
            # TODO: Integrate with Spotify API, MPD, or local media player
            return {"success": True, "action": action, "genre": genre, "mood": mood, "status": "playing"}
            
        elif intent.type in [IntentType.STOP_MUSIC, IntentType.PAUSE_MUSIC]:
            # TODO: Send pause command
            return {"success": True, "action": action, "status": "paused"}
            
        return {"success": True, "action": action, "status": "executed"}
