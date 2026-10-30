from src.tasks.registry import TaskRegistry, BaseTaskHandler
from src.nlu.intent import IntentType, Intent

@TaskRegistry.register(IntentType.DEVICE_ON)
@TaskRegistry.register(IntentType.DEVICE_OFF)
@TaskRegistry.register(IntentType.DEVICE_STATUS)
class DeviceHandler(BaseTaskHandler):
    """Handles smart device and IoT API calls (Home Assistant, Hue, etc.)."""
    
    def execute(self, intent: Intent) -> dict:
        device_name = intent.get_entity("device_name", "unknown device")
        location = intent.get_entity("device_location", "unknown location")
        
        # TODO: Send API request to Smart Home Hub
        
        state = "on" if intent.type == IntentType.DEVICE_ON else "off"
        if intent.type == IntentType.DEVICE_STATUS:
            state = "unknown"
            
        return {
            "success": True,
            "device": device_name,
            "location": location,
            "new_state": state,
            "message": f"Successfully turned {state} the {device_name} in the {location}."
        }
