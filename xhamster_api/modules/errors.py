# This module contains custom exceptions, because I do not want to re-raise the errors from eaf_base_api
from base_api.modules.errors import (
    NotFound,
    NetworkError,
    BotDetection,
    ProxyError,
    UnknownNetworkError,
    DownloadFailed,
)


class LoginFailed(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


__all__ = [
    "NotFound",
    "NetworkError",
    "BotDetection",
    "ProxyError",
    "UnknownNetworkError",
    "DownloadFailed",
    "LoginFailed",
]

