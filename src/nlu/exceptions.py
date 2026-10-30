"""Exception hierarchy for the NLU package."""


class NLUError(Exception):
    """Base exception for all NLU-related errors."""


class PreprocessingError(NLUError):
    """Raised when text preprocessing/normalization fails."""


class ClassificationError(NLUError):
    """Raised when intent classification fails unexpectedly."""


class EntityExtractionError(NLUError):
    """Raised when entity extraction fails unexpectedly."""
