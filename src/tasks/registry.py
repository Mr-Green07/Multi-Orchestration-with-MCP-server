import logging
from abc import ABC, abstractmethod
from typing import Dict, Type, Any

# pyrefly: ignore [missing-import]
from src.nlu.intent import Intent, IntentType
# pyrefly: ignore [missing-import]
from src.tasks.exceptions import HandlerNotFoundError, TaskExecutionError

logger = logging.getLogger(__name__)

class BaseTaskHandler(ABC):
    """
    The abstract base class that ALL task handlers must inherit from.
    Every handler must implement the `execute` method.
    """
    
    @abstractmethod
    def execute(self, intent: Intent) -> Dict[str, Any]:
        """
        Executes the business logic for the given intent.
        
        :param intent: The parsed Intent object from the NLU layer.
        :return: A dictionary containing the result of the execution.
                 This will be passed to the LLM to generate a natural response.
                 Example: {"success": True, "weather_summary": "72 degrees and sunny"}
        """
        pass


class TaskRegistry:
    """
    Central router that maps an IntentType to its specific BaseTaskHandler.
    """
    _registry: Dict[IntentType, Type[BaseTaskHandler]] = {}

    @classmethod
    def register(cls, intent_type: IntentType):
        """
        A decorator to easily register a new handler class.
        
        Example:
            @TaskRegistry.register(IntentType.GET_WEATHER)
            class WeatherHandler(BaseTaskHandler):
                def execute(self, intent): ...
        """
        def wrapper(handler_class: Type[BaseTaskHandler]):
            if not issubclass(handler_class, BaseTaskHandler):
                raise TypeError(f"{handler_class.__name__} must inherit from BaseTaskHandler.")
            
            if intent_type in cls._registry:
                logger.warning(f"Overwriting existing handler for intent '{intent_type.value}'.")
                
            cls._registry[intent_type] = handler_class
            logger.debug(f"Registered {handler_class.__name__} for intent '{intent_type.value}'.")
            return handler_class
        return wrapper

    @classmethod
    def get_handler(cls, intent_type: IntentType) -> BaseTaskHandler:
        """
        Retrieves an INSTANCE of the handler registered for the given intent.
        
        :raises HandlerNotFoundError: If no handler has been registered for this intent.
        """
        handler_class = cls._registry.get(intent_type)
        if not handler_class:
            logger.error(f"No handler registered for intent: {intent_type.value}")
            raise HandlerNotFoundError(
                f"Cannot execute task: No handler found for intent '{intent_type.value}'."
            )
            
        # Instantiate and return the handler
        return handler_class()
