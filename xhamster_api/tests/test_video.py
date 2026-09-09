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


def test_video_extract_html_fallback():
    from unittest.mock import MagicMock
    from ..api import Video

    html_snippet = """<body eid2="1">
<div class="main-wrap" data-role="main-wrap"><main class="video-type-video">
    <div class="width-wrap with-player-container">
        <div data-role="video-heading">
            <div class="root-3e2be isDesktopSite-3e2be isExpanded-3e2be"><div class="sizer-3e2be isDesktopSite-3e2be isExpanded-3e2be"><hgroup class="hgroup-3e2be"><h1 class="h3-bold-8643e primary-8643e title-3e2be">Passionate Homemade Sex with Big Cock - Missionary, Doggy, Spooning &amp; Pussy Licking</h1> <div class="aside-3e2be isDesktopSite-3e2be"> <p class="primary-8643e icons-a993a"><span class="root-33e82 primary-33e82 xh-icon eyeIcon-a993a" aria-label="121356 views"><svg viewBox="0 0 20 20" width="20" class="icon-33e82"><use id="eye" xlink:href="/icons.base.6a3df639.svg#eye"></use></svg></span> <span class="primary-8643e" aria-hidden="true">121.356</span> <span class="root-33e82 primary-33e82 xh-icon likeIcon-a993a" aria-label="97% likes"><svg viewBox="0 0 20 20" width="20" class="icon-33e82"><use id="like" xlink:href="/icons.base.6a3df639.svg#like"></use></svg></span> <span class="primary-8643e" aria-hidden="true">97%</span></p> </div></hgroup></div></div>
        </div>

        <nav id="video-tags-list-container">
            <div class="container-5f2e3 desktop-2252c container-2252c" style="max-height: 32px;" data-role="video-tags-list" eid2="3"><div class="list-5f2e3 collapsed-5f2e3">
                <div class="item-50dd2 tag-2252c"><a class="container-5984a primary-5984a tag-96c3e" href="https://xhamster.com/pornstars/sumiko-smile"><span class="body-bold-8643e label-5984a label-96c3e">Sumiko Smile</span></a></div>
                <div class="item-50dd2 tag-2252c"><a class="container-5984a primary-5984a tag-96c3e" href="https://xhamster.com/pornstars/tim-deen"><span class="body-8643e label-5984a label-96c3e">Tim Deen</span></a></div>
                <div class="item-50dd2 tag-2252c"><a class="container-5984a primary-5984a tag-96c3e" href="https://xhamster.com/categories/amateur"><span class="body-8643e label-5984a label-96c3e">Amateur</span></a></div>
                <div class="item-50dd2 tag-2252c"><a class="container-5984a primary-5984a tag-96c3e" href="https://xhamster.com/categories/big-cock"><span class="body-8643e label-5984a label-96c3e">Big Cock</span></a></div>
                <div class="item-50dd2 tag-2252c"><a class="container-5984a primary-5984a tag-96c3e" href="https://xhamster.com/tags/sex"><span class="body-8643e label-5984a label-96c3e">Sex</span></a></div>
                <div class="item-50dd2 tag-2252c"><a class="container-5984a primary-5984a tag-96c3e" href="https://xhamster.com/tags/hot"><span class="body-8643e label-5984a label-96c3e">Hot</span></a></div>
            </div></div>
        </nav>

        <div class="player-container">
            <div class="player-container__player xplayer notranslate xp-progress-bar-full" id="player-container" data-role="xplayer" tabindex="-1">
                <div class="xp-preload-image" style="background-image: url('https://ic-vt-nss.xhcdn.com/a/ZjY3ZTlmZDAxMmFiNDRkY2Q0NjI0ZjI1YmNlZDQxNGM/s(w:1280,h:720),webp/030/651/885/v2/2560x1440.218.webp');"></div>
                <noscript>
                    <video class="player-container__no-script-video" preload="auto"
                           src="https://video7.xhcdn.com/key=bE97wdofCsu8xcclubDaDQ,end=1788944400,limit=3/data=2a02:6ea0:1703:8185::38-dvp/speed=0/030/651/885/480p.h264.mp4"
                           poster="https://ic-vt-nss.xhcdn.com/a/ZjY3ZTlmZDAxMmFiNDRkY2Q0NjI0ZjI1YmNlZDQxNGM/s(w:1280,h:720),webp/030/651/885/v2/2560x1440.218.webp" controls playsinline></video>
                </noscript>
                <div class="timing"><span class="played">00:00</span><span class="separator">/</span><span class="eta">08:12</span></div>
            </div>
            <div class="xp-settings-inner-list settings-menu xh-helper-hidden">
                <span class="quality chooser-control xp-settings-inner-list-inner">
                    <span data-value="auto" class="chosen auto-chosen">auto</span>
                    <span data-value="1080p" class="HD">1080p</span>
                    <span data-value="720p" class="HD">720p</span>
                    <span data-value="480p">480p</span>
                </span>
            </div>
            <a href="https://video7.xhcdn.com/key=bE97wdofCsu8xcclubDaDQ,end=1788944400,limit=3/data=2a02:6ea0:1703:8185::38-dvp/speed=0/030/651/885/480p.h264.mp4" class="player-container__no-player"></a>
        </div>

        <div class="controls" eid2="4">
            <div class="rb-new" id="dyltv-anchor">
                <div class="rb-new__container">
                    <button class="root-64d24 ratingButtonLike-a6242"></button>
                    <p class="primary-8643e rb-new__info" data-tooltip="97%" aria-label="421 likes, 15 dislikes">
                        <span class="primary-8643e" aria-hidden="true">421 / 15</span>
                    </p>
                    <button class="root-64d24 ratingButtonDislike-a6242"></button>
                </div>
            </div>
            <div class="controls__main-actions">
                <div class="controls__main-action comments-control">
                    <button class="xh-button button button-c7c46"><span class="button__body">Comments <span class="count-c7c46">2</span></span></button>
                </div>
            </div>
        </div>

        <div class="controls-info">
            <div class="ab-info controls-info__item xh-helper-hidden" data-role="controls-info">
                <p class="controls-info__description"></p>
                <div class="entity-info-container__published-row">
                    <div class="entity-info-container__author entity-author-container">
                        Published by <a class="entity-author-container__name" href="https://xhamster.com/users/sumiko_smile"><span>Sumiko_Smile</span></a>
                    </div>
                    <div class="entity-info-container__date tooltip-nocache" data-tooltip="2026-09-04 09:21:36 UTC">
                        4 days ago
                    </div>
                </div>
            </div>
        </div>
    </div>
</main>
<aside class="bottom-cb57f"><a class="root-64d24 small-64d24 secondary-64d24 version-cb57f" href="https://xhamster.com/videos/passionate-homemade-sex-with-big-cock-missionary-doggy-spooning-pussy-licking-xh7bsA5?x_platform_switch=mobile">Mobile Version</a></aside>
</div>
</body>"""

    video = Video(
        core=MagicMock(),
        url="https://xhamster.com/videos/passionate-homemade-sex-with-big-cock-missionary-doggy-spooning-pussy-licking-xh7bsA5",
    )
    data = video._extract_html(html_snippet)

    assert data["title"] == "Passionate Homemade Sex with Big Cock - Missionary, Doggy, Spooning & Pussy Licking"
    assert data["video_id"] == 30651885
    assert data["video_hash"] == "xh7bsA5"
    assert data["likes"] == 421
    assert data["dislikes"] == 15
    assert data["rating_percentage"] == 97
    assert data["views"] == 121356
    assert data["comments_count"] == 2
    assert data["duration"] == 492
    assert data["uploader_name"] == "Sumiko Smile" or data["uploader_name"] == "Sumiko_Smile"
    assert "Amateur" in data["categories"]
    assert "Sex" in data["tags"]
    assert "Sumiko Smile" in data["pornstars"]
    assert data["is_hd"] is True
    assert data["max_resolution"] == "1080p"
    assert data["created_timestamp"] == "2026-09-04 09:21:36 UTC"
    assert data["date_ago"] == "4 days ago"
    assert "https://" in data["thumbnail"]
    assert "https://" in data["m3u8_base_url"]


