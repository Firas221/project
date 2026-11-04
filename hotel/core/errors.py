"""Application error hierarchy.

Every error a client may legitimately see derives from :class:`AppError` and
carries an HTTP status. Anything else is treated as an internal error and its
details are never sent to the client.
"""


class AppError(Exception):
    status = 500
    default_message = "Internal server error"

    def __init__(self, message: str = None, *, field: str = None):
        self.message = message or self.default_message
        self.field = field
        super().__init__(self.message)

    def to_dict(self) -> dict:
        data = {"error": self.message}
        if self.field:
            data["field"] = self.field
        return data


class ValidationError(AppError):
    status = 400
    default_message = "Invalid input"


class AuthenticationError(AppError):
    status = 401
    default_message = "Please sign in"


class PermissionDenied(AppError):
    status = 403
    default_message = "You do not have permission to do this"


class NotFound(AppError):
    status = 404
    default_message = "Not found"


class MethodNotAllowed(AppError):
    status = 405
    default_message = "Method not allowed"


class Conflict(AppError):
    status = 409
    default_message = "The request conflicts with the current state"


class PayloadTooLarge(AppError):
    status = 413
    default_message = "Request body too large"


class UnsupportedMediaType(AppError):
    status = 415
    default_message = "Content-Type must be application/json"


class RateLimited(AppError):
    status = 429
    default_message = "Too many requests. Please slow down."
