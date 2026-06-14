"""Base application error for the API error envelope.

Any AppError (or subclass) is turned by the FastAPI handler into the contract's
{ "error": { "code", "message" } } response, using its status_code and code.
Subclasses live with their concern (auth, management, scoring).
"""


class AppError(Exception):
    status_code: int = 400
    code: str = "app_error"
