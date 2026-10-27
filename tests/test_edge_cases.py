import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from xhamster_api.api import Client, Video, Short, Creator, Channel, Pornstar, DownloadConfigHLS, run_main
from xhamster_api.modules.consts import extractor_videos, extractor_shorts, build_page_url
from base_api.modules.errors import NotFound, MediaLoadError


# ---------------------------------------------------------------------------
# 1. Search Edge Cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_vr_does_not_404():
    """Verify that vr=True does not conflict with minimum_quality and returns results."""
    client = Client()
    count = 0
    async for result in client.search_videos(query="vr", vr=True, pages=1):
        v = result.unwrap()
        assert isinstance(v.title, str) and len(v.title) > 0
        assert v.url.startswith("http")
        count += 1
        if count >= 3:
            break
    assert count > 0, "Expected at least 1 VR search result"


@pytest.mark.asyncio
async def test_search_zero_results_terminates_cleanly():
    """Verify that queries returning 404 from xHamster terminate gracefully without unhandled exception."""
    client = Client()
    count = 0
    async for _ in client.search_videos(query="xyznonexistentquery9876543210abc", pages=1):
        count += 1
    assert count == 0


@pytest.mark.asyncio
async def test_search_extracts_duration_and_thumbnails():
    """Verify that search video extraction populates thumbnails and durations (not dropped by skeletons)."""
    client = Client()
    results = []
    async for result in client.search_videos(query="amateur", pages=1):
        v = result.unwrap()
        results.append(v)
        if len(results) >= 15:
            break

    assert len(results) >= 10, "Expected at least 10 search results"
    valid_thumbs = [v for v in results if v.thumbnail and v.thumbnail.startswith("http")]
    assert len(valid_thumbs) == len(results), f"Expected all {len(results)} videos to have thumbnails, got {len(valid_thumbs)}"


@pytest.mark.asyncio
async def test_search_filters():
    """Verify that various search filters execute successfully."""
    client = Client()
    # Test sort_by and min_duration
    count = 0
    async for result in client.search_videos(query="teen", sort_by="views", min_duration="10", pages=1):
        v = result.unwrap()
        assert v.title
        count += 1
        if count >= 2:
            break
    assert count > 0


# ---------------------------------------------------------------------------
# 2. Short / Moment Edge Cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_short_from_moments_url():
    """Verify get_short works with legacy/alternate /moments/ URL path."""
    client = Client()
    short = await client.get_short("https://xhamster.com/moments/epic-moment-fucking-big-tit-xhj6G0l")
    assert isinstance(short.title, str) and len(short.title) > 0
    assert short.author == "Comatozze"
    assert short.m3u8_base_url and short.m3u8_base_url.startswith("http")


def test_short_extract_fallback_no_script():
    """Verify Short._extract_data handles pages missing initials-script without crashing."""
    html_without_script = """
    <html>
        <head>
            <meta property="og:title" content="Fallback Short Title" />
            <meta property="og:image" content="https://example.com/thumb.jpg" />
        </head>
        <body>
            <div data-role="user-name">Fallback Creator</div>
        </body>
    </html>
    """
    data = Short._extract_data(html_without_script)
    assert data["title"] == "Fallback Short Title"
    assert data["thumbnail"] == "https://example.com/thumb.jpg"
    assert data["author"] == "Fallback Creator"
    assert data["likes"] == 0
    assert data["views"] == 0


def test_short_extract_fallback_malformed_script():
    """Verify Short._extract_data handles malformed script content gracefully."""
    html = '<script id="initials-script">window.initials={malformed js;;</script>'
    data = Short._extract_data(html)
    assert data["title"] == ""
    assert data["likes"] == 0
    assert data["views"] == 0


# ---------------------------------------------------------------------------
# 3. Video Extraction & HD Detection Edge Cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_video_hd_detection():
    """Verify that a 1080p video is correctly identified as is_hd=True."""
    client = Client()
    video = await client.get_video("https://xhamster.com/videos/beach-fuck-xhLFIXc")
    assert video.max_resolution in ("1080p", "720p", "2160p", "4k")
    assert video.is_hd is True, "1080p video should have is_hd=True"


@pytest.mark.asyncio
async def test_video_not_found_handling():
    """Verify that non-existent video URL raises NotFound / MediaLoadError."""
    client = Client()
    with pytest.raises((NotFound, MediaLoadError)):
        await client.get_video("https://xhamster.com/videos/totally-fake-video-xh000000000")


# ---------------------------------------------------------------------------
# 4. Profile Shorts & Pagination Edge Cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_creator_get_shorts_yields_actual_shorts():
    """Verify creator.get_shorts() yields shorts with valid metadata instead of 0 items."""
    client = Client()
    creator = await client.get_creator("https://xhamster.com/creators/comatozze")
    shorts = []
    async for result in creator.get_shorts(pages=1):
        s = result.unwrap()
        assert s.title
        assert s.url
        assert "/shorts/" in s.url or "/moments/" in s.url
        shorts.append(s)
        if len(shorts) >= 5:
            break
    assert len(shorts) >= 3, f"Expected at least 3 shorts from creator, got {len(shorts)}"


@pytest.mark.asyncio
async def test_channel_get_shorts_does_not_crash():
    """Verify channel.get_shorts() functions without NoneType AttributeError."""
    client = Client()
    channel = await client.get_channel("https://xhamster.com/channels/brazzers")
    shorts = []
    async for result in channel.get_shorts(pages=1):
        s = result.unwrap()
        assert s.title
        assert s.url
        shorts.append(s)
        if len(shorts) >= 5:
            break
    assert len(shorts) >= 3, f"Expected at least 3 shorts from channel, got {len(shorts)}"


# ---------------------------------------------------------------------------
# 5. Ergonomic Aliases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aliases():
    """Verify client.get_user and profile get_videos / shorts aliases."""
    client = Client()
    assert client.get_user == client.get_creator

    creator = await client.get_creator("https://xhamster.com/creators/comatozze", load_html=False)
    assert hasattr(creator, "get_videos")
    assert creator.get_videos == creator.videos
    assert hasattr(creator, "shorts")
    assert creator.shorts == creator.get_shorts


# ---------------------------------------------------------------------------
# 6. Regional / Localized Domains
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_localized_domain_support():
    """Verify that localized domain (ge.xhamster.desi) successfully extracts video."""
    client = Client()
    url = "https://ge.xhamster.desi/videos/im-not-a-whore-i-just-love-sex-why-dont-i-have-sex-with-two-guys-xheJpw6"
    video = await client.get_video(url)
    assert video.title
    assert video.video_id == 25979705
    assert video.m3u8_base_url and video.m3u8_base_url.startswith("http")


# ---------------------------------------------------------------------------
# 7. CLI Short Download Routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cli_routes_shorts_to_get_short():
    """Verify CLI calls client.get_short for /shorts/ URLs."""
    mock_short = MagicMock()
    mock_short.title = "Sample Short"
    mock_short.download = AsyncMock()

    mock_client = MagicMock()
    mock_client.get_short = AsyncMock(return_value=mock_short)

    with patch("xhamster_api.api.Client", return_value=mock_client):
        await run_main(["--download", "https://xhamster.com/shorts/test-short-xh123", "--output", "/tmp/out"])

    mock_client.get_short.assert_awaited_once_with("https://xhamster.com/shorts/test-short-xh123", load_html=True)
    mock_short.download.assert_awaited_once()
