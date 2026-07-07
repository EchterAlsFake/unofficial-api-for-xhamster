import pytest
from ..api import Client


@pytest.mark.asyncio
async def test_creator():
    client = Client()
    creator = await client.get_creator("https://xhamster.com/creators/comatozze")
    assert isinstance(creator.name, str) and len(creator.name) > 1
    assert isinstance(creator.subscribers_count, str) and len(creator.subscribers_count) > 1
    assert isinstance(creator.videos_count, str) and len(creator.videos_count) > 1
    assert isinstance(creator.total_views_count, str) and len(creator.total_views_count) > 1
    assert isinstance(creator.avatar_url, str) and len(creator.avatar_url) > 1
    assert isinstance(creator.pornstar_creator_information, dict) and len(creator.pornstar_creator_information.keys()) > 1

    idx = 0
    async for result in creator.videos():
        idx += 1
        assert isinstance(result.video.title, str) and len(result.video.title) > 1

        if idx >= 3:
            break

    idx = 0
    async for result in creator.get_shorts():
        idx += 1
        assert isinstance(result.video.title, str) and len(result.video.title) > 1

        if idx >= 3:
            break
