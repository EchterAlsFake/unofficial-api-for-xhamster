import logging

__all__ = ["Client", "Video", "consts"]

from xhamster_api.api import Client, Video
from xhamster_api.modules import consts

logging.getLogger(__name__).addHandler(logging.NullHandler())