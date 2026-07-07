import pytest
from ..api import Client


@pytest.mark.asyncio
async def test_search():
    client = Client()
    idx = 0
    async for result in client.search_videos(query="polly yangs"):
        idx += 1
        assert isinstance(result.video.title, str) and len(result.video.title) > 1


        if idx >= 3:
            break
