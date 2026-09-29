class OpenRouterError(Exception):
    """Base exception with a safe message suitable for the application UI."""

    user_message = "L’assistant IA est momentanément indisponible. Réessayez plus tard."


class OpenRouterConfigurationError(OpenRouterError):
    user_message = "L’assistant IA n’est pas encore configuré."


class OpenRouterAuthenticationError(OpenRouterError):
    user_message = "L’assistant IA n’est pas disponible en raison de sa configuration."


class OpenRouterRateLimitError(OpenRouterError):
    user_message = "L’assistant reçoit trop de demandes. Réessayez dans quelques instants."


class OpenRouterTimeoutError(OpenRouterError):
    user_message = "L’assistant a mis trop de temps à répondre. Réessayez."


class OpenRouterServiceError(OpenRouterError):
    pass


class OpenRouterResponseError(OpenRouterError):
    user_message = "La réponse de l’assistant est inutilisable. Réessayez."
