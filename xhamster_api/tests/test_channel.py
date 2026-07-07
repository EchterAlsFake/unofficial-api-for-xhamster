import pytest
from ..api import Client


@pytest.mark.asyncio
async def test_channel():
    client = Client()
    channel = await client.get_channel("https://xhamster.com/channels/brazzers")
    assert isinstance(channel.name, str) and len(channel.name) > 1
    assert isinstance(channel.subscribers_count, str) and len(channel.subscribers_count) > 0
    assert isinstance(channel.videos_count, str) and len(channel.videos_count) > 0
    assert isinstance(channel.total_views_count, str) and len(channel.total_views_count) > 0
    assert isinstance(channel.avatar_url, str) and len(channel.avatar_url) > 0


    idx = 0
    async for result in channel.videos():
        idx += 1
        assert isinstance(result.video.title, str) and len(result.video.title) > 1

        if idx >= 3:
            break

    idx = 0
    async for result in channel.get_shorts():
        idx += 1
        assert isinstance(result.video.title, str) and len(result.video.title) > 1

        if idx >= 3:
            break
