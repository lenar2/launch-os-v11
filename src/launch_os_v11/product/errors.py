class ProductError(Exception):
    """A product action the room refused or could not finish honestly."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
