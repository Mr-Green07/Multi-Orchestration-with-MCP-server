from src.utils.exceptions import AppError

class TaskError(AppError):
    """
    Base exception for everything in the Task Execution layer.
    
    This fires when the NLU successfully figures out what the user wants to do 
    (the Intent), but the actual execution of that intent fails.
    
    Examples:
      - We try to turn on a device, but the smart home API is down.
      - We try to set a timer, but the time duration entity is missing.
      - A task handler crashes unexpectedly during execution.
    """
    pass


class HandlerNotFoundError(TaskError):
    """
    Raised when the Task Executor receives a valid Intent (e.g. "play_music"),
    but there is no Python script or function registered to actually handle it.
    
    Examples:
      - The user added "open_garage" to nlu_config.json, but forgot to write 
        a handler for it in src/tasks/handlers/.
      - The routing dictionary in the task registry is missing a mapping 
        for a specific IntentType.
    """
    pass

class TaskExecutionError(TaskError):
    """
    Raised when a handler is found and starts running, but fails mid-execution.
    
    Examples:
      - The Weather handler is called, but the external Weather API returns a 500 error.
      - The Music handler tries to play a song that doesn't exist.
    """
    pass
