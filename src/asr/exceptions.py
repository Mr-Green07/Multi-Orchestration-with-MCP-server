class ASRException(Exception):
    # pyrefly: ignore [bad-function-definition]
    def __init__(self, message: str, error_code: str = None):
        self.message = message
        self.error_code = error_code or "UNKNOWN_ERROR"
        super().__init__(self.message)
    
    def __str__(self) -> str:
        # Return formatted error message with error code.
        return f"[{self.error_code}] {self.message}"

# Audio-related exceptions

class AudioException(ASRException):
    """Base exception for audio processing errors."""
    pass

class InvalidAudioFormatError(AudioException):

    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        format_received: str = None,
        # pyrefly: ignore [bad-function-definition]
        format_expected: str = None,
        error_code: str = "INVALID_AUDIO_FORMAT"
    ):
        self.format_received = format_received
        self.format_expected = format_expected
        super().__init__(message, error_code)


class AudioProcessingError(AudioException):
       
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        chunk_size: int = None,
        error_code: str = "AUDIO_PROCESSING_ERROR"
    ):
        self.chunk_size = chunk_size
        super().__init__(message, error_code)


class AudioQueueError(AudioException):
    
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        queue_size: int = None,
        error_code: str = "AUDIO_QUEUE_ERROR"
    ):
        self.queue_size = queue_size
        super().__init__(message, error_code)


# Model-related exceptions

class ModelException(ASRException):
    pass

class ModelNotFoundError(ModelException):
   
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        model_name: str = None,
        # pyrefly: ignore [bad-function-definition]
        model_path: str = None,
        error_code: str = "MODEL_NOT_FOUND"
    ):
        self.model_name = model_name
        self.model_path = model_path
        super().__init__(message, error_code)


class ModelLoadError(ModelException):

    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        model_name: str = None,
        # pyrefly: ignore [bad-function-definition]
        root_cause: Exception = None,
        error_code: str = "MODEL_LOAD_ERROR"
    ):
        self.model_name = model_name
        self.root_cause = root_cause
        super().__init__(message, error_code)


class UnsupportedModelError(ModelException):
   
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        model_name: str = None,
        # pyrefly: ignore [bad-function-definition]
        supported_models: list = None,
        error_code: str = "UNSUPPORTED_MODEL"
    ):
        
        self.model_name = model_name
        self.supported_models = supported_models or []
        super().__init__(message, error_code)

# Transcription-related exceptions

class TranscriptionException(ASRException):
    """Base exception for transcription-related errors."""
    pass

class TranscriptionError(TranscriptionException):
    
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        audio_duration: float = None,
        # pyrefly: ignore [bad-function-definition]
        audio_file: str = None,
        error_code: str = "TRANSCRIPTION_ERROR"
    ):
        self.audio_duration = audio_duration
        self.audio_file = audio_file
        super().__init__(message, error_code)


class TranscriptionTimeoutError(TranscriptionException):
   
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        timeout_seconds: float = None,
        # pyrefly: ignore [bad-function-definition]
        audio_file: str = None,
        error_code: str = "TRANSCRIPTION_TIMEOUT"
    ):
        self.timeout_seconds = timeout_seconds
        self.audio_file = audio_file
        super().__init__(message, error_code)

class LanguageDetectionError(TranscriptionException):
    
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        detected_language: str = None,
        # pyrefly: ignore [bad-function-definition]
        confidence: float = None,
        # pyrefly: ignore [bad-function-definition]
        supported_languages: list = None,
        error_code: str = "LANGUAGE_DETECTION_ERROR"
    ):
        self.detected_language = detected_language
        self.confidence = confidence
        self.supported_languages = supported_languages or []
        super().__init__(message, error_code)


# Configuration-related exceptions

class ConfigurationException(ASRException):
    pass


class InvalidConfigurationError(ConfigurationException):

    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        parameter_name: str = None,
        # pyrefly: ignore [not-a-type]
        invalid_value: any = None,
        # pyrefly: ignore [bad-function-definition]
        valid_range: tuple = None,
        error_code: str = "INVALID_CONFIGURATION"
    ):
        self.parameter_name = parameter_name
        self.invalid_value = invalid_value
        self.valid_range = valid_range
        super().__init__(message, error_code)


class ConfigurationFileError(ConfigurationException):
   
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        config_file: str = None,
        # pyrefly: ignore [bad-function-definition]
        root_cause: Exception = None,
        error_code: str = "CONFIGURATION_FILE_ERROR"
    ):
       
        self.config_file = config_file
        self.root_cause = root_cause
        super().__init__(message, error_code)


# Processing-related exceptions

class ProcessingException(ASRException):
    pass


class ProcessingTimeoutError(ProcessingException):

    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        timeout_seconds: float = None,
        # pyrefly: ignore [bad-function-definition]
        chunks_processed: int = None,
        error_code: str = "PROCESSING_TIMEOUT"
    ):
       
        self.timeout_seconds = timeout_seconds
        self.chunks_processed = chunks_processed
        super().__init__(message, error_code)


class ProcessingStateError(ProcessingException):    
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        current_state: str = None,
        # pyrefly: ignore [bad-function-definition]
        expected_state: str = None,
        error_code: str = "PROCESSING_STATE_ERROR"
    ):
        
        self.current_state = current_state
        self.expected_state = expected_state
        super().__init__(message, error_code)


class ProcessingError(ProcessingException):
    def __init__(
        self,
        message: str,
        # pyrefly: ignore [bad-function-definition]
        root_cause: Exception = None,
        error_code: str = "PROCESSING_ERROR"
    ):
        
        self.root_cause = root_cause
        super().__init__(message, error_code)
