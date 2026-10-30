class AppError(Exception):
    """
    Base exception class for the ASR application.
    
    All custom exceptions across the project (like ASRError, 
    ResponseGenerationError, etc.) should inherit from this base class.
    This allows the application to easily catch and handle any known 
    internal errors gracefully.
    """
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self):
        if self.details:
            return f"{self.message} (Details: {self.details})"
        return self.message
