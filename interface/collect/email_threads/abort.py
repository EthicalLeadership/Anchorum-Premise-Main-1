class ParsingAbort(Exception):
    """Raised when a safety bound is exceeded."""
    def __init__(self, reason: str, message_id: str = None):
        self.reason = reason
        self.message_id = message_id
        super().__init__(reason)
