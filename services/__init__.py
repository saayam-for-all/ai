"""
Service module with abstraction layer for easy provider switching.
Python 3.14+ compatible.
"""
from abc import ABC, abstractmethod
import os


class ClassificationServiceInterface(ABC):
    """Abstract interface for category classification services."""
    
    @abstractmethod
    def predict_categories(self, subject: str, description: str) -> str:
        """
        Predict categories based on subject and description.
        
        Args:
            subject: The subject of the user's request
            description: The description of the user's request
            
        Returns:
            str: Predicted category
        """
        pass


class AnswerGenerationServiceInterface(ABC):
    """Abstract interface for answer generation services."""
    
    @abstractmethod
    def generate_answer(
        self, 
        category: str, 
        subject: str, 
        description: str, 
        location: str | None = None, 
        gender: str | None = None,
        age: str | None = None,
        conversation_history: list[dict[str, str]] | None = None
    ) -> str:
        """
        Generate a conversational answer with context maintenance.
        
        Args:
            category: The category for the answer
            subject: The subject of the user's request
            description: The current user message/question
            location: The location of the user
            gender: Optional gender information
            age: Optional age information
            conversation_history: Optional list of previous messages in format [{"role": "user/assistant", "content": "..."}]
            
        Returns:
            str: Generated answer
        """
        pass


class ServiceWrapper:
    """
    Wrapper class that provides unified access to all services.
    This abstraction allows easy switching between providers without affecting clients.
    """
    
    # Provider registry (lazy loaded to avoid circular imports)
    _classification_providers = {}
    _answer_generation_providers = {}
    
    DEFAULT_PROVIDER = "groq"
    
    def __init__(
        self,
        provider: str | None = None,
        classification_kwargs: dict | None = None,
        answer_generation_kwargs: dict | None = None
    ):
        """
        Initialize the service wrapper.
        
        Args:
            provider: Service provider name (e.g., 'groq'). If None, uses env var or default
            classification_kwargs: Optional kwargs for classification service initialization
            answer_generation_kwargs: Optional kwargs for answer generation service initialization
        """
        self.provider = provider or os.getenv("SERVICE_PROVIDER", self.DEFAULT_PROVIDER)
        classification_kwargs = classification_kwargs or {}
        answer_generation_kwargs = answer_generation_kwargs or {}
        
        # Lazy load providers to avoid circular imports
        if not ServiceWrapper._classification_providers:
            from services.classification_service import GroqClassificationService
            from services.generate_answer_service import GroqAnswerGenerationService
            ServiceWrapper._classification_providers = {"groq": GroqClassificationService}
            ServiceWrapper._answer_generation_providers = {"groq": GroqAnswerGenerationService}
        
        # Initialize classification service
        if self.provider not in ServiceWrapper._classification_providers:
            raise ValueError(
                f"Unknown provider: {self.provider}. "
                f"Available providers: {list(ServiceWrapper._classification_providers.keys())}"
            )
        
        classification_class = ServiceWrapper._classification_providers[self.provider]
        self.classification_service: ClassificationServiceInterface = classification_class(
            **classification_kwargs
        )
        
        # Initialize answer generation service with classification service injected
        if self.provider not in ServiceWrapper._answer_generation_providers:
            raise ValueError(
                f"Unknown provider: {self.provider}. "
                f"Available providers: {list(ServiceWrapper._answer_generation_providers.keys())}"
            )
        
        answer_generation_class = ServiceWrapper._answer_generation_providers[self.provider]
        answer_generation_kwargs['classification_service'] = self.classification_service
        
        self.answer_generation_service: AnswerGenerationServiceInterface = answer_generation_class(
            **answer_generation_kwargs
        )
    
    def predict_categories(self, subject: str, description: str) -> str:
        """
        Predict categories based on subject and description.
        
        Args:
            subject: The subject of the user's request
            description: The description of the user's request
            
        Returns:
            str: Predicted category
        """
        return self.classification_service.predict_categories(subject, description)
    
    def generate_answer(
        self,
        category: str,
        subject: str,
        description: str,
        location: str | None = None,
        gender: str | None = None,
        age: str | None = None,
        conversation_history: list[dict[str, str]] | None = None
    ) -> str:
        """
        Generate a conversational answer with context maintenance.
        
        Args:
            category: The category for the answer
            subject: The subject of the user's request
            description: The current user message/question
            location: The location of the user
            gender: Optional gender information
            age: Optional age information
            conversation_history: Optional list of previous messages in format [{"role": "user/assistant", "content": "..."}]
            
        Returns:
            str: Generated answer
        """
        return self.answer_generation_service.generate_answer(
            category, subject, description, location, gender, age, conversation_history
        )
    
    @classmethod
    def register_classification_provider(cls, name: str, service_class):
        """Register a new classification service provider."""
        if not issubclass(service_class, ClassificationServiceInterface):
            raise ValueError("Service class must implement ClassificationServiceInterface")
        cls._classification_providers[name.lower()] = service_class
    
    @classmethod
    def register_answer_generation_provider(cls, name: str, service_class):
        """Register a new answer generation service provider."""
        if not issubclass(service_class, AnswerGenerationServiceInterface):
            raise ValueError("Service class must implement AnswerGenerationServiceInterface")
        cls._answer_generation_providers[name.lower()] = service_class


# Global service wrapper instance (singleton pattern)
_service_wrapper: ServiceWrapper | None = None


def get_service_wrapper() -> ServiceWrapper:
    """
    Get the global service wrapper instance.
    Creates it if it doesn't exist (lazy initialization).
    
    Returns:
        ServiceWrapper: The global service wrapper instance
    """
    global _service_wrapper
    if _service_wrapper is None:
        _service_wrapper = ServiceWrapper()
    return _service_wrapper


def reset_service_wrapper():
    """Reset the global service wrapper (useful for testing or provider switching)."""
    global _service_wrapper
    _service_wrapper = None

