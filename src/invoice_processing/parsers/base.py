"""Types shared by every parser. Parsers must not import intake."""


class ExtractionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
