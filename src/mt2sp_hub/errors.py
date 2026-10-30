"""Stable public errors without local paths or raw exception details."""


class HubError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise HubError(code, message)
