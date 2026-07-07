import pytest
from ..api import Client


@pytest.mark.asyncio
async def test_pornstar():
    client = Client()
    pornstar = await client.get_pornstar("https://xhamster.com/pornstars/polly-yangs")
    assert isinstance(pornstar.name, str) and len(pornstar.name) > 1
    assert isinstance(pornstar.subscribers_count, str) and len(pornstar.subscribers_count) > 1
    assert isinstance(pornstar.videos_count, str) and len(pornstar.videos_count) > 1
    assert isinstance(pornstar.total_views_count, str) and len(pornstar.total_views_count) > 1
    assert isinstance(pornstar.avatar_url, str) and len(pornstar.avatar_url) > 1
    assert isinstance(pornstar.pornstar_creator_information, dict) and len(pornstar.pornstar_creator_information.keys()) > 0

    idx = 0
    async for result in pornstar.videos():
        idx += 1
        assert isinstance(result.video.title, str) and len(result.video.title) > 1

        if idx >= 3:
            break


    idx = 0
    async for result in pornstar.get_shorts():
        idx += 1
        assert isinstance(result.video.title, str) and len(result.video.title) > 1

        if idx >= 3:
            break

