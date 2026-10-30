from src.utils.exceptions import AppError

class DatabaseError(AppError):
    """
    Base exception for all local storage and SQLite database operations.
    Raised when the system fails to read/write from the local DB.
    """
    pass

class RecordNotFoundError(DatabaseError):
    """
    Raised when querying the database for a specific record that does not exist.
    
    Examples:
      - Trying to fetch a user profile that hasn't been created yet.
      - Attempting to load an API key that was deleted or never set.
    """
    pass
