"""Word Pulse AI failure categories shared by classification and reporting."""


class WordPulseAIError(Exception):
    """Base AI failure."""


class WordPulseAIConfigError(WordPulseAIError):
    """Invalid AI configuration or request."""


class WordPulseAITimeoutError(WordPulseAIError):
    """AI request exceeded its time budget."""


class WordPulseAIAuthError(WordPulseAIError):
    """AI authentication or authorization failed."""


class WordPulseAIServiceError(WordPulseAIError):
    """AI transport or service failed."""


class WordPulseAIResponseError(WordPulseAIError):
    """AI output failed validation."""
