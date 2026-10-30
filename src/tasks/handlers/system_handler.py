from src.tasks.registry import TaskRegistry, BaseTaskHandler
from src.nlu.intent import IntentType, Intent
from src.utils.device_apis import DeviceController

@TaskRegistry.register(IntentType.VOLUME_UP)
@TaskRegistry.register(IntentType.VOLUME_DOWN)
@TaskRegistry.register(IntentType.SET_VOLUME)
@TaskRegistry.register(IntentType.SYSTEM_SHUTDOWN)
@TaskRegistry.register(IntentType.SYSTEM_RESTART)
@TaskRegistry.register(IntentType.SYSTEM_STATUS)
class SystemHandler(BaseTaskHandler):
    """Handles OS-level volume, brightness, and system controls."""
    
    def execute(self, intent: Intent) -> dict:
        
        if intent.type == IntentType.VOLUME_UP:
            DeviceController.volume_up(steps=4)
            return {"success": True, "action": "volume_up"}
            
        elif intent.type == IntentType.VOLUME_DOWN:
            DeviceController.volume_down(steps=4)
            return {"success": True, "action": "volume_down"}
            
        elif intent.type == IntentType.SET_VOLUME:
            # Requires more advanced OS bindings for setting absolute volume,
            # but we extract it here.
            level = intent.get_entity("volume_level")
            return {"success": True, "action": "set_volume", "target_level": level}
            
        # TODO: Handle shutdown/restart commands safely
        return {"success": True, "action": intent.type.value}
