class AppError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500
    default_message = "Internal error"

    def __init__(self, message: str | None = None, *, details: dict | None = None) -> None:
        self.message = self.default_message if message is None else message
        self.details = details
        super().__init__(self.message)
