from src.tasks.registry import TaskRegistry, BaseTaskHandler
from src.nlu.intent import IntentType, Intent

@TaskRegistry.register(IntentType.GET_WEATHER)
@TaskRegistry.register(IntentType.GET_FORECAST)
@TaskRegistry.register(IntentType.SEARCH_WEB)
@TaskRegistry.register(IntentType.TELL_JOKE)
@TaskRegistry.register(IntentType.GET_NEWS)
class KnowledgeHandler(BaseTaskHandler):
    """Handles external API lookups and general knowledge questions."""
    
    def execute(self, intent: Intent) -> dict:
        
        if intent.type == IntentType.GET_WEATHER:
            # We would typically parse an entity here, e.g. location
            location = intent.get_entity("location", "your current location")
            # TODO: Add OpenWeatherMap API call
            return {
                "success": True,
                "location": location,
                "weather": "Sunny",
                "temperature": 75,
                "message": "It is sunny and 75 degrees."
            }
            
        elif intent.type == IntentType.TELL_JOKE:
            # Fallback local joke or API call
            return {
                "success": True,
                "joke": "Why do programmers prefer dark mode? Because light attracts bugs!"
            }
            
        return {"success": True, "action": intent.type.value, "status": "executed dummy knowledge handler"}
