class PromptForgeException(Exception):
    """PromptForge基础异常。"""


class ConfigurationError(PromptForgeException):
    pass


class DatabaseError(PromptForgeException):
    pass


class ProviderError(PromptForgeException):
    pass


class ModelUnavailableError(ProviderError):
    pass


class NetworkError(ProviderError):
    pass


class ParserError(PromptForgeException):
    pass


class ValidationError(PromptForgeException):
    pass


class TaskError(PromptForgeException):
    pass


class PluginError(PromptForgeException):
    pass
