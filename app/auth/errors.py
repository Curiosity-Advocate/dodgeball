"""Auth domain errors.

Every auth failure inherits AuthError, which carries the HTTP status and the
envelope error code. A single FastAPI handler (in app.api) turns any AuthError
into the contract's { "error": { "code", "message" } } response.
"""


class AuthError(Exception):
    """Base for auth failures. Subclasses set status_code and code."""

    status_code: int = 400
    code: str = "auth_error"


class InvalidCredentials(AuthError):
    status_code = 401
    code = "invalid_credentials"

    def __init__(self, message: str = "Invalid email or password") -> None:
        super().__init__(message)


class EmailAlreadyExists(AuthError):
    status_code = 409
    code = "email_taken"

    def __init__(self, message: str = "Email already registered") -> None:
        super().__init__(message)


class InvalidAccessToken(AuthError):
    status_code = 401
    code = "invalid_token"


class InvalidRefreshToken(AuthError):
    status_code = 401
    code = "invalid_refresh_token"


class RefreshTokenReused(AuthError):
    status_code = 401
    code = "token_reused"


class RateLimited(AuthError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str = "Too many attempts, slow down") -> None:
        super().__init__(message)
