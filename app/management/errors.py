"""Management domain errors."""

from app.core.errors import AppError


class MatchNotFound(AppError):
    status_code = 404
    code = "match_not_found"

    def __init__(self, message: str = "Match not found") -> None:
        super().__init__(message)


class InvalidReference(AppError):
    status_code = 422
    code = "invalid_reference"

    def __init__(self, message: str = "Referenced entity does not exist") -> None:
        super().__init__(message)
