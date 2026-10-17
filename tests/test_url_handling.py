"""Offline regressions for URL identity, pagination and listing contracts."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from xhamster_api import api as api


class EmptyStream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class UrlHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def test_filtered_profile_fetches_two_distinct_pages(self):
        media = api.Creator(url="https://ge.xhamster.desi/creators/Example/newest/9?tag=example#videos", core=object())
        capture = Mock(return_value=EmptyStream())
        from contextlib import ExitStack

        with ExitStack() as stack:
            for name in ("scrape_stream", "_scrape_stream"):
                if hasattr(api, name):
                    stack.enter_context(patch.object(api, name, capture))
            if hasattr(api, "Helper"):
                stack.enter_context(patch.object(api, "Helper", lambda **kwargs: SimpleNamespace(iterator=capture)))
            stack.enter_context(patch.object(api.Creator, "get_field", AsyncMock(return_value=2)))
            async for _ in media.videos(pages=2):
                pass
        urls = capture.call_args.kwargs["target_page_urls"]
        self.assertEqual(
            urls,
            [
                "https://ge.xhamster.desi/creators/Example/newest?tag=example",
                "https://ge.xhamster.desi/creators/Example/newest/2?tag=example",
            ],
        )


if __name__ == "__main__":
    unittest.main()
