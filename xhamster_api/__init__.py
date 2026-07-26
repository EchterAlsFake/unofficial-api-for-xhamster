import logging

__all__ = ["Client", "Video", "consts", "DownloadConfigHLS"]

from xhamster_api.api import Client, Video, DownloadConfigHLS
from xhamster_api.modules import consts

logging.getLogger(__name__).addHandler(logging.NullHandler())