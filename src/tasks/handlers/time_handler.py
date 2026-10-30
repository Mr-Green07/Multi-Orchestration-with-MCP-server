import time
from datetime import datetime
from src.tasks.registry import TaskRegistry, BaseTaskHandler
from src.nlu.intent import IntentType, Intent

@TaskRegistry.register(IntentType.GET_TIME)
@TaskRegistry.register(IntentType.GET_DATE)
@TaskRegistry.register(IntentType.SET_TIMER)
@TaskRegistry.register(IntentType.CANCEL_TIMER)
class TimeHandler(BaseTaskHandler):
    """Handles time, date, and local timer logic."""
    
    def execute(self, intent: Intent) -> dict:
        now = datetime.now()
        
        if intent.type == IntentType.GET_TIME:
            current_time = now.strftime("%I:%M %p")
            return {"success": True, "time": current_time, "context": "Current local time."}
            
        elif intent.type == IntentType.GET_DATE:
            current_date = now.strftime("%A, %B %d, %Y")
            return {"success": True, "date": current_date, "context": "Current local date."}
            
        elif intent.type == IntentType.SET_TIMER:
            duration = intent.get_entity("duration")
            # TODO: Spawn a background thread to wait `duration` and trigger an alarm.
            return {"success": True, "action": "set_timer", "duration": duration}
            
        return {"success": False, "reason": "Not implemented"}
