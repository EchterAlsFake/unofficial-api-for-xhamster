import pytest
from ..api import Client, DownloadConfigHLS


@pytest.mark.asyncio
async def test_short():
    try:
        import av
    except:
        raise "Can't run without AV"

    client = Client()
    short = await client.get_short("https://xhamster.com/shorts/teen-jerks-pussy-shower-xhecgTc")


    assert isinstance(short.title, str) and len(short.title) > 1
    assert isinstance(short.author, str) and len(short.author) > 1
    assert isinstance(short.likes, int) and len(str(short.likes)) > 1
    assert isinstance(short.views, int) and len(str(short.views)) > 1
    assert isinstance(short.comment_count, int) and len(str(short.comment_count)) > 1
    assert isinstance(short.duration, int) and len(str(short.duration)) > 1
    assert isinstance(short.video_id, int) and len(str(short.video_id)) > 1
    assert isinstance(short.created_at, int) and len(str(short.created_at)) > 1
    assert isinstance(short.tags, list) and len(short.tags) > 1
    assert isinstance(short.author_subscribers, int) and len(str(short.author_subscribers)) > 1
    assert isinstance(short.author_logo, str) and len(short.author_logo) > 1
    assert isinstance(short.author_link, str) and len(short.author_link) > 1
    assert isinstance(short.thumbnail, str) and len(short.thumbnail) > 1
    assert isinstance(short.poster_url, str) and len(short.poster_url) > 1
    assert isinstance(short.m3u8_base_url, str) and len(short.m3u8_base_url) > 1

    config = DownloadConfigHLS(quality="best", return_report=True)
    result = await short.download(config)
    assert result.status == "completed"


