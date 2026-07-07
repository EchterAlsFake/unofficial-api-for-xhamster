from operator import and_

import pytest
from ..api import Client, DownloadConfigHLS


@pytest.mark.asyncio
async def test_all_video():
    try:
        import av
    except (ModuleNotFoundError, ImportError):
        raise "Can't run tests without av installed!"

    client = Client()
    video = await client.get_video("https://xhamster.com/videos/im-not-a-whore-i-just-love-sex-why-dont-i-have-sex-with-two-guys-xheJpw6")

    assert isinstance(video.title, str) and len(video.title) > 1
    assert isinstance(video.video_id, int) and len(str(video.video_id)) > 1
    assert isinstance(video.m3u8_base_url, str) and len(video.m3u8_base_url) > 1
    assert isinstance(video.likes, int) and len(str(video.likes)) > 0
    assert isinstance(video.dislikes, int) and len(str(video.dislikes)) > 0
    assert isinstance(video.categories, list) and len(video.categories) > 1
    assert isinstance(video.tags, list) and len(video.tags) > 1
    assert isinstance(video.pornstars, list) and len(video.pornstars) > 1
    assert isinstance(video.rating_percentage, int) and len(str(video.rating_percentage)) > 1
    assert isinstance(video.thumbnail, str) and len(video.thumbnail) > 1
    assert isinstance(video.uploader_name, str) and len(video.uploader_name) > 1
    assert isinstance(video.uploader_subscribers, int) and len(str(video.uploader_subscribers)) >= 0

    config = DownloadConfigHLS(quality="worst", return_report=True)
    config_2 = DownloadConfigHLS(quality="worst", return_report=True, remux=True)

    status_1 = await video.download(config)
    assert status_1["status"] == "completed"

    status_2 = await video.download(config_2)
    assert status_2["status"] == "completed"

