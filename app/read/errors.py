"""Read domain errors."""

from app.core.errors import AppError


class NotFound(AppError):
    status_code = 404
    code = "not_found"

    def __init__(self, message: str = "Not found") -> None:
        super().__init__(message)
