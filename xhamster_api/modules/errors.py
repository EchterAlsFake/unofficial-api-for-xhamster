# This module contains custom exceptions, because I do not want to re-raise the errors from eaf_base_api
from base_api.modules.errors import (
    ScraperException,
    LoginFailed,
    NotFound,
    NetworkError,
    BotDetection,
    ProxyError,
    UnknownNetworkError,
    DownloadFailed,
)




__all__ = [
    "NotFound",
    "NetworkError",
    "BotDetection",
    "ProxyError",
    "UnknownNetworkError",
    "DownloadFailed",
    "LoginFailed",
]
