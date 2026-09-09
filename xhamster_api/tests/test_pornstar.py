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
    assert isinstance(pornstar.pornstar_information, dict) and len(pornstar.pornstar_information.keys()) > 0

    idx = 0
    async for result in pornstar.videos():
        idx += 1
        video = result.unwrap()
        assert isinstance(video.title, str) and len(video.title) > 1

        if idx >= 3:
            break


    idx = 0
    async for result in pornstar.get_shorts():
        idx += 1
        video = result.unwrap()
        assert isinstance(video.title, str) and len(video.title) > 1

        if idx >= 3:
            break


def test_pornstar_extract_data_from_html():
    from unittest.mock import MagicMock
    from ..api import Pornstar

    html_snippet = """<div class="main-wrap" data-role="main-wrap">
        <article class="pornstar-container">
            <div data-role="pornstar-info" class="category-info pornstar">
                <div class="landing-info">
                    <div class="landing-info__logo-image" style="background-image: url('https://ic-tt-nss.xhcdn.com/a/MGE4YjIwMDViMjEyZTdjMDhlNjk4ZDBkOGEyMGEzMzM/webp/000/056/576/avatar1.jpg.v1607075319');"></div>
                    <p class="h3-bold-8643e primary-8643e landing-info__user-title">Mia Khalifa</p>
                    <div class="landing-info__metric">
                        <div class="h3-bold-8643e primary-8643e landing-info__metric-value">268.3K</div>
                        <p class="small-regular-8643e secondary-8643e landing-info__metric-text">subscribers</p>
                    </div>
                    <div class="landing-info__metric">
                        <div class="h3-bold-8643e primary-8643e landing-info__metric-value">195</div>
                        <p class="small-regular-8643e secondary-8643e landing-info__metric-text">videos</p>
                    </div>
                    <div class="landing-info__metric">
                        <div class="h3-bold-8643e primary-8643e landing-info__metric-value">982.6M</div>
                        <p class="small-regular-8643e secondary-8643e landing-info__metric-text">views</p>
                    </div>
                    <div class="landing-info__metric aliases" data-tooltip="Mia Callista, Mia Khalifia, Mia K">
                        <p class="small-regular-8643e secondary-8643e landing-info__metric-text">Mia Callista, Mia Khalifia, Mia K</p>
                    </div>
                </div>
            </div>
            <div data-role="pornstar-about-me">
                <div class="aboutMe-68bbb">
                    <div class="personalInfo-5360e">
                        <ul class="list-b51e4">
                            <li class="item-b51e4">
                                <div class="label-b51e4">I am:</div>
                                <div class="value-b51e4">Female</div>
                            </li>
                            <li class="item-b51e4">
                                <div class="label-b51e4">From:</div>
                                <div class="value-b51e4">Lebanon</div>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        </article>
    </div>"""

    mock_core = MagicMock()
    pornstar = Pornstar(url="https://xhamster.com/pornstars/mia-khalifa", core=mock_core)
    data = pornstar._extract_data(html_snippet)

    assert data["name"] == "Mia Khalifa"
    assert data["subscribers_count"] == "268.3K"
    assert data["videos_count"] == "195"
    assert data["total_views_count"] == "982.6M"
    assert data["avatar_url"] == "https://ic-tt-nss.xhcdn.com/a/MGE4YjIwMDViMjEyZTdjMDhlNjk4ZDBkOGEyMGEzMzM/webp/000/056/576/avatar1.jpg.v1607075319"
    assert data["pornstar_information"] == {"I am:": "Female", "From:": "Lebanon"}


def test_pornstar_extract_data_fallbacks(caplog):
    import logging
    from unittest.mock import MagicMock
    from ..api import Pornstar

    # Test completely empty/broken page layout triggers anchor & field warnings
    mock_core = MagicMock()
    pornstar = Pornstar(url="https://xhamster.com/pornstars/unknown", core=mock_core)
    with caplog.at_level(logging.WARNING):
        data = pornstar._extract_data("<html><body><div>empty</div></body></html>")

    assert data["name"] is None
    assert data["subscribers_count"] is None
    assert data["videos_count"] is None
    assert data["total_views_count"] is None
    assert data["avatar_url"] is None
    assert data["pornstar_information"] == {}
    assert any("Layout anchor" in record.message for record in caplog.records)

    # Test positional fallback when metric text labels are absent
    caplog.clear()
    html_positional_metrics = """
    <div class="landing-info">
        <h1 class="page-title">Custom Star</h1>
        <div class="landing-info__metric">
            <div class="landing-info__metric-value">100K</div>
        </div>
        <div class="landing-info__metric">
            <div class="landing-info__metric-value">50</div>
        </div>
        <div class="landing-info__metric">
            <div class="landing-info__metric-value">1.2M</div>
        </div>
    </div>
    """
    data2 = pornstar._extract_data(html_positional_metrics)
    assert data2["name"] == "Custom Star"
    assert data2["subscribers_count"] == "100K"
    assert data2["videos_count"] == "50"
    assert data2["total_views_count"] == "1.2M"

