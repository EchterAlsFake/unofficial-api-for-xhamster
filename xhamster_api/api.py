from __future__ import annotations

import os
import urllib
import logging
import chompjs
import asyncio

from dataclasses import dataclass
from functools import cached_property
from urllib.parse import urlencode, quote
from curl_cffi import AsyncSession, Response
from selectolax.lexbor import LexborHTMLParser
from base_api.modules.config import RuntimeConfig
from base_api.modules.type_hints import DownloadReport
from typing import Literal, AsyncGenerator, Any, Dict, List
from base_api import DownloadConfigHLS, ScrapeResult, BaseCore, setup_logger, Helper
from base_api.modules.errors import NetworkRequestError, BotProtectionDetected, UnknownError, InvalidProxy, ResourceGone

from xhamster_api.modules.errors import (NetworkError, UnknownNetworkError, NotFound, BotDetection, ProxyError,
                                         DownloadFailed)
from xhamster_api.modules.consts import (build_page_url, extractor_shorts, headers, REGEX_AVATAR, REGEX_M3U8,
                                        REGEX_THUMBNAIL, REGEX_AUTHOR)
from xhamster_api.modules.type_hints import on_error_hint


async def on_error(url: str, error: Exception, attempt: int) -> bool:
    print(f"URL: {url}, ERROR: {error}, Attempt: {attempt}")

    if isinstance(error, ResourceGone):
        return False

    return True

async def get_html_content(core: BaseCore, url: str) -> str | None | dict:
    # What should I do here?
    try:
        content = await core.fetch(url)
        if isinstance(content, str):
            return content

        if isinstance(content, Response):
            if content.status_code == 404:
                raise NotFound(f"Server returned 404 for: {url}")

    except NetworkRequestError as e:
        raise NetworkError(str(e)) from e

    except InvalidProxy as e:
        raise ProxyError(str(e)) from e

    except BotProtectionDetected as e:
        raise BotDetection(str(e)) from e

    except UnknownError as e:
        raise UnknownNetworkError(str(e)) from e


@dataclass(slots=True)
class ShortMetadata:
    title: str
    author: str
    likes: int
    dislikes: int
    views: int
    comments: int
    duration: int
    video_id: int
    created_at: int
    tags: list[str]
    author_subscribers: int
    author_logo: str
    author_link: str
    thumb_url: str
    poster_url: str
    m3u8_bas_url: str


class Something(Helper):
    def __init__(self, lexbor: LexborHTMLParser, url: str, core: BaseCore,
                 html_content: str):
        super().__init__(core, video_constructor=VideoBuilder, log_level=logging.ERROR, alternative_constructor=ShortBuilder)
        self.url = url
        self.html_content = html_content
        self.lexbor: LexborHTMLParser = lexbor

    @classmethod
    async def init(cls, url: str, core: BaseCore, html_content: str | None = None) -> Something:
        if not html_content:
            response = await core.fetch(url)
            # Ensure we have a string for BeautifulSoup
            if response is None:
                html_content = ""
            elif not isinstance(response, str):
                html_content = getattr(response, "text", str(response))
            else:
                html_content = response

        lexbor = LexborHTMLParser(html_content)
        return cls(lexbor=lexbor, url=url, core=core, html_content=html_content)

    def _find_text(self, name: str, index: int = 0) -> str:
        """Safely find a tag and return its stripped text, or an empty string."""
        tag = self.lexbor.css(name)[index]
        return tag.text(strip=True) if tag else ""

    @cached_property
    def name(self) -> str:
        return self._find_text("h1.h3-bold-8643e.primary-8643e.landing-info__user-title")

    @cached_property
    def subscribers_count(self) -> str:
        return self._find_text("div.body-8643e.primary-8643e.landing-info__metric-value")

    @cached_property
    def videos_count(self) -> str:
        return self._find_text("div.body-8643e.primary-8643e.landing-info__metric-value", index=1)

    @cached_property
    def total_views_count(self) -> str:
        return self._find_text("div.body-8643e.primary-8643e.landing-info__metric-value", index=2)

    @cached_property
    def avatar_url(self) -> str:
        return REGEX_AVATAR.search(self.html_content).group(1)

    async def videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False
                     ) -> AsyncGenerator[ScrapeResult, None]:
        page_urls = [build_page_url(url=self.url, is_search=False, idx=page) for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for scrape_result in self.iterator(use_alternative_constructor=True, video_link_extractor=extractor_shorts,
                                 max_video_concurrency=videos_concurrency, max_page_concurrency=pages_concurrency,
                                 on_video_error=on_video_error, on_page_error=on_page_error, target_page_urls=page_urls,
                                 keep_original_order=keep_original_order):
            yield scrape_result


    async def get_shorts(self, pages: int = 2, videos_concurrency: int = 2, pages_concurrency: int = 1,
                         on_video_error: on_error_hint = on_error,
                         on_page_error: on_error_hint = None,
                         keep_original_order: bool = False
                         ) -> AsyncGenerator[ScrapeResult, None]:
        if not self.url.endswith("/"):
            self.url += "/"

        self.url += "shorts"
        page_urls = [build_page_url(self.url, is_search=False, idx=page) for page in range(1, pages + 1)]
        async for scrape_result in self.iterator(use_alternative_constructor=True, video_link_extractor=extractor_shorts,
                                 target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                 max_page_concurrency=pages_concurrency, on_video_error=on_video_error,
                                 on_page_error=on_page_error, keep_original_order=keep_original_order):
            yield scrape_result


class Channel(Something):
    pass


class Pornstar(Something):

    @cached_property
    def name(self) -> str:
        return self._find_text("h2.h3-bold-8643e.primary-8643e.landing-info__user-title")

    @cached_property
    def get_information(self) -> Dict[str, str] | None:
        container = self.lexbor.css_first("div.personalInfo-5360e")
        if not container:
            return None # No User Information present...

        li_tags = container.css("li")
        fortnite = self.lexbor.css("ul.list-b51e4")
        if len(fortnite) > 1:
            li_tags.extend(fortnite[1].css("li"))

        dictionary = {}

        for li_tag in li_tags:
            divs = li_tag.css("div")
            if len(divs) >= 2:
                key = divs[0].text(strip=True)
                value = divs[1].text(strip=True)
                dictionary[key] = value

        return dictionary

class Creator(Something):

    @cached_property
    def name(self) -> str:
        return self._find_text("h2.h3-bold-8643e.primary-8643e.landing-info__user-title")

    @cached_property
    def get_information(self) -> Dict[str, str] | None:
        container = self.lexbor.css_first("div.personalInfo-5360e")
        if not container:
            return None # No User Information present...

        li_tags = container.css("li")
        fortnite = self.lexbor.css("ul.list-b51e4")
        if len(fortnite) > 1:
            li_tags.extend(fortnite[1].css("li"))

        dictionary = {}

        for li_tag in li_tags:
            divs = li_tag.css("div")
            if len(divs) >= 2:
                key = divs[0].text(strip=True)
                value = divs[1].text(strip=True)
                dictionary[key] = value

        return dictionary

class Short:
    __slots__ = ("metadata", "core")

    def __init__(self, metadata: ShortMetadata, core: BaseCore):
        self.metadata = metadata
        self.core = core

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def likes(self) -> int:
        return self.metadata.likes

    @property
    def dislikes(self) -> int:
        return self.metadata.dislikes

    @property
    def views(self) -> int:
        return self.metadata.views

    @property
    def comments(self) -> int:
        return self.metadata.comments

    @property
    def duration(self) -> int:
        return self.metadata.duration

    @property
    def video_id(self) -> int:
        return self.metadata.video_id

    @property
    def created_at(self) -> int:
        return self.metadata.created_at

    @property
    def tags(self) -> list[str]:
        return self.metadata.tags

    @property
    def author(self) -> str:
        return self.metadata.author

    @property
    def author_subscribers(self) -> int:
        return self.metadata.author_subscribers

    @property
    def author_logo(self) -> str:
        return self.metadata.author_logo

    @property
    def author_link(self) -> str:
        return self.metadata.author_link

    @property
    def thumb_url(self) -> str:
        return self.metadata.thumb_url

    @property
    def poster_url(self) -> str:
        return self.metadata.poster_url

    @property
    def m3u8_base_url(self) -> str:
        return self.metadata.m3u8_bas_url

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        """
        :param configuration:
        :return:
        """

        if not configuration.no_title:
            configuration.path = os.path.join(configuration.path, f"{self.title}.mp4")

        configuration.m3u8_base_url = self.m3u8_base_url

        try:
            return await self.core.download(configuration=configuration)

        except Exception as e:
            raise DownloadFailed(str(e))


class ShortBuilder:
    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        self.core = core
        self.url = url
        self.logger = setup_logger(name="XHamster API - [Short]")
        self.html_content = html_content

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.clean()

    def _extract_from_html(self):
        meta = ShortMetadata(
            title=self.title,
            dislikes=self.dislikes,
            tags=self.tags,
            thumb_url=self.thumb_url,
            video_id=self.video_id,
            comments=self.comments,
            duration=self.duration,
            created_at=self.created_at,
            poster_url=self.poster_url,
            author_link=self.author_link,
            author_logo=self.author_logo,
            m3u8_bas_url=self.m3u8_base_url,
            likes=self.likes,
            views=self.views,
            author_subscribers=self.author_subscribers,
            author=self.author,
        )

        short = Short(metadata=meta, core=self.core)
        return short

    async def clean(self) -> None:
        self.core = None
        self.url = None
        self.html_content = None
        self.logger = None
        self.data = None

    async def init(self) -> Short:
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)
            assert self.html_content

        return await asyncio.to_thread(self._extract_from_html)

    @cached_property
    def data(self) -> dict:
        assert self.html_content
        lexbor = LexborHTMLParser(self.html_content)
        script = lexbor.css_first("script#initials-script").text()
        # Extract the JSON part after 'window.initials='
        json_text = script.split("window.initials=", 1)[-1].strip().rstrip(";")
        return chompjs.parse_js_object(json_text)

    @cached_property
    def title(self) -> str:
        return self.data.get('layoutPage', {}).get('momentProps', {}).get('title', '')

    @cached_property
    def author(self) -> str:
        author = self.data.get('layoutPage', {}).get('momentProps', {}).get('landing', {}).get('name')
        return str(author) if author else ""

    @cached_property
    def likes(self) -> int:
        likes = self.data.get('layoutPage', {}).get('momentProps', {}).get('ratingModel', {}).get('likes')
        return int(likes) if likes is not None else 0

    @cached_property
    def dislikes(self) -> int:
        dislikes = self.data.get('layoutPage', {}).get('momentProps', {}).get('ratingModel', {}).get('dislikes')
        return int(dislikes) if dislikes is not None else 0

    @cached_property
    def views(self) -> int:
        views = self.data.get('layoutPage', {}).get('momentProps', {}).get('views')
        return int(views) if views is not None else 0

    @cached_property
    def comments(self) -> int:
        comments = self.data.get('layoutPage', {}).get('momentProps', {}).get('comments')
        return int(comments) if comments is not None else 0

    @cached_property
    def duration(self) -> int:
        duration = self.data.get('xplayerSettings', {}).get('duration')
        return int(duration) if duration is not None else 0

    @cached_property
    def video_id(self) -> int:
        video_id = self.data.get('xplayerSettings', {}).get('videoId')
        if not video_id:
             video_id = self.data.get('layoutPage', {}).get('momentProps', {}).get('id')
        return int(video_id) if video_id is not None else 0

    @cached_property
    def created_at(self) -> int:
        created = self.data.get('layoutPage', {}).get('momentProps', {}).get('created')
        return int(created) if created is not None else 0

    @cached_property
    def tags(self) -> List[str]:
        tags = self.data.get('layoutPage', {}).get('momentProps', {}).get('tags', [])
        return [tag.get('name') for tag in tags if tag.get('name')]

    @cached_property
    def author_subscribers(self) -> int:
        subscribers = self.data.get('layoutPage', {}).get('momentProps', {}).get('landing', {}).get('subscribers')
        return int(subscribers) if subscribers is not None else 0

    @cached_property
    def author_logo(self) -> str:
        return self.data.get('layoutPage', {}).get('momentProps', {}).get('landing', {}).get('logo', '')

    @cached_property
    def author_link(self) -> str:
        return self.data.get('layoutPage', {}).get('momentProps', {}).get('landing', {}).get('link', '')

    @cached_property
    def thumb_url(self) -> str:
        return self.data.get('layoutPage', {}).get('momentProps', {}).get('thumbUrl', '')

    @cached_property
    def poster_url(self) -> str:
        return self.data.get('layoutPage', {}).get('momentProps', {}).get('posterUrl', '')

    @cached_property
    def m3u8_base_url(self) -> str:
        url = self.data.get('xplayerSettings', {}).get('sources', {}).get('hls', {}).get('h264', {}).get('url')
        if not url:
            url = self.data.get('layoutPage', {}).get('momentProps', {}).get('sources', {}).get('hls', {}).get('h264', {}).get('url')
        return str(url) if url else ""


@dataclass(slots=True)
class VideoMetadata:
    title: str
    video_id: int | None
    rating_percentage: int
    likes: int
    dislikes: int
    _uploader_tag_model: Dict[str, Any]
    uploader_name: str
    uploader_subscribers: int
    categories: list[str]
    tags: list[str]
    pornstars: list[str]
    thumbnail: str
    m3u8_base_url: str


class Video:
    __slots__ = ["metadata", "core"]
    def __init__(self, metadata: VideoMetadata, core: BaseCore):
        self.metadata = metadata
        self.core = core

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def video_id(self) -> int | None:
        return self.metadata.video_id

    @property
    def rating_percentage(self) -> int:
        return self.metadata.rating_percentage

    @property
    def likes(self) -> int:
        return self.metadata.likes

    @property
    def dislikes(self) -> int:
        return self.metadata.dislikes

    @property
    def _uploader_tag_model(self) -> Dict[str, Any]:
        return self.metadata._uploader_tag_model

    @property
    def uploader_name(self) -> str:
        return self.metadata.uploader_name

    @property
    def uploader_subcribers(self) -> int:
        return self.metadata.uploader_subscribers

    @property
    def categories(self) -> list[str]:
        return self.metadata.categories

    @property
    def tags(self) -> list[str]:
        return self.metadata.tags

    @property
    def pornstars(self) -> list[str]:
        return self.metadata.pornstars

    @property
    def thumbnail(self) -> str:
        return self.metadata.thumbnail

    @property
    def m3u8_base_url(self) -> str:
        return self.metadata.m3u8_base_url

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        """
        :param configuration:
        :return:
        """

        if not configuration.no_title:
            configuration.path = os.path.join(configuration.path, f"{self.title}.mp4")

        configuration.m3u8_base_url = self.m3u8_base_url

        try:
            return await self.core.download(configuration=configuration)

        except Exception as e:
            raise DownloadFailed(str(e))



class VideoBuilder:
    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        self.core = core
        self.url = url
        self.logger = setup_logger(name="XHamster API - [Video]")
        self.html_content = html_content

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.clean()

    async def init(self) -> Video:
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        return await asyncio.to_thread(self._extract_from_html)

    async def clean(self) -> None:
        self.html_content = None
        self.logger = None
        self.url = None
        self.core = None

    def _extract_from_html(self) -> Video:
        meta = VideoMetadata(
            title=self.title,
            video_id=self.video_id,
            rating_percentage=self.rating_percentage,
            dislikes=self.dislikes,
            likes=self.likes,
            _uploader_tag_model=self._uploader_tag_model,
            uploader_name=self.uploader_name,
            uploader_subscribers=self.uploader_subscribers,
            pornstars=self.pornstars,
            thumbnail=self.thumbnail,
            categories=self.categories,
            m3u8_base_url=self.m3u8_base_url,
            tags=self.tags,
        )

        video = Video(metadata=meta, core=self.core)
        return video

    def enable_logging(self, log_file: str | None = None, level: int = logging.DEBUG, log_ip: str | None = None, log_port: int | None = None) -> None:
        self.logger = setup_logger(name="XHamster API - [Video]", level=level, log_file=log_file, http_ip=log_ip, http_port=log_port)

    @cached_property
    def data(self) -> dict:
        assert self.html_content
        lexbor = LexborHTMLParser(self.html_content)
        script = lexbor.css_first("script#initials-script").text()
        # Extract the JSON part after 'window.initials='
        json_text = script.split("window.initials=", 1)[-1].strip().rstrip(";")
        return chompjs.parse_js_object(json_text)

    @cached_property
    def video_id(self) -> int | None:
        """Extracts the unique numerical ID of the video."""
        return self.data.get("videoTagsComponent", {}).get("videoId")

    @cached_property
    def title(self) -> str:
        """Extracts and decodes the video title.

        Note: In this specific payload, the plain text title is nested
        inside an advertising/widget callback URL, so we parse it out cleanly.
        """
        data_url = (
            self.data.get("bannerUnderComments", {})
            .get("fh", {})
            .get("dataUrl", "")
        )
        if data_url:
            parsed_url = urllib.parse.urlparse(data_url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            titles = query_params.get("videoTitle", [])
            if titles:
                return urllib.parse.unquote_plus(titles[0])
        return ""

    @cached_property
    def rating_percentage(self) -> int:
        """Returns the user approval rating percentage (e.g., 99)."""
        return (
            self.data.get("ratingComponent", {})
            .get("ratingModel", {})
            .get("value", 0)
        )

    @cached_property
    def likes(self) -> int:
        """Total number of upvotes/likes."""
        return (
            self.data.get("ratingComponent", {})
            .get("ratingModel", {})
            .get("likes", 0)
        )

    @cached_property
    def dislikes(self) -> int:
        """Total number of downvotes/dislikes."""
        return (
            self.data.get("ratingComponent", {})
            .get("ratingModel", {})
            .get("dislikes", 0)
        )

    @cached_property
    def _uploader_tag_model(self) -> Dict[str, Any]:
        """Internal helper to find the tag object representing the uploader."""
        tags = self.data.get("videoTagsComponent", {}).get("tags", [])
        for tag in tags:
            if tag.get("isUser"):
                return tag
        return {}

    @cached_property
    def uploader_name(self) -> str:
        """The username of the content creator/uploader."""
        return self._uploader_tag_model.get("name", "")

    @cached_property
    def uploader_subscribers(self) -> int:
        """The total subscriber count of the uploader."""
        sub_model = self._uploader_tag_model.get("subscriptionModel") or {}
        return sub_model.get("subscribers", 0)

    @cached_property
    def categories(self) -> List[str]:
        """Returns a list of high-level site categories assigned to the video

        (e.g., ['Colombian', '3D', 'Big Tits']).
        """
        tags = self.data.get("videoTagsComponent", {}).get("tags", [])
        return [
            tag["name"]
            for tag in tags
            if tag.get("isCategory") and "name" in tag
        ]

    @cached_property
    def tags(self) -> List[str]:
        """Returns a list of micro-tags assigned to the video

        (e.g., ['Hot MILF', 'Anime Hentai']).
        """
        tags = self.data.get("videoTagsComponent", {}).get("tags", [])
        return [
            tag["name"] for tag in tags if tag.get("isTag") and "name" in tag
        ]


    @cached_property
    def pornstars(self) -> List[str]:
        matches = REGEX_AUTHOR.findall(self.html_content)
        actual_pornstars = []
        for match in matches:
            actual_pornstars.append(match[1])

        return actual_pornstars

    @cached_property
    def thumbnail(self) -> str:
        return REGEX_THUMBNAIL.search(self.html_content).group(1)

    @cached_property
    def m3u8_base_url(self) -> str:
        url =  REGEX_M3U8.search(self.html_content).group(0)
        fixed_url = url.replace("\\/", "/")  # Fixing escaped slashes
        self.logger.debug(f"M3U8 URL: {fixed_url}")
        return fixed_url


class Client(Helper):
    def __init__(self, core: BaseCore = BaseCore(RuntimeConfig())):
        super().__init__(core=core, video_constructor=VideoBuilder)
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(headers)

    async def get_video(self, url: str) -> Video:
        video = VideoBuilder(url, core=self.core)
        return await video.init()

    async def get_pornstar(self, url: str) -> Pornstar:
        return await Pornstar.init(url=url, core=self.core)

    async def get_creator(self, url: str) -> Creator:
        return await Creator.init(url=url, core=self.core)

    async def get_channel(self, url: str) -> Channel:
        return await Channel.init(url=url, core=self.core)

    async def get_short(self, url: str) -> Short:
        short = ShortBuilder(url, core=self.core)
        return await short.init()

    async def search_videos(self, query: str,
        minimum_quality: Literal["720p", "1080p", "2160p"] = "720p",
        sort_by: Literal["views", "newest", "best", "longest"] | None = None, # Empty string sorts by relevance

        category: Literal["german", "amateur", "18-year-old", "granny", "anal", "old-young", "mature",
        "mom", "milf", "big-tits", "big-natural-tits", "lesbian", "teen", "cum-in-mouth", "bdsm",
        "porn-for-women", "russian", "vintage", "hairy", "brutal-sex"] | List[str] | None = None ,
        vr: bool = False,
        full_length_only: bool = False,
        min_duration: Literal["2", "5", "10", "30", "40"] | None = None,
        date: Literal["latest", "weekly", "monthly", "yearly"] | None = None,
        production: Literal["studios", "creators"] | None = None,
        fps: Literal["30", "60"] | None = None,
        pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None,
                            on_video_error: on_error_hint = on_error,
                            on_page_error: on_error_hint = None,
                            keep_original_order: bool = False
                            ) -> AsyncGenerator[ScrapeResult, None]:
        path = quote(str(query), safe="")  # e.g. "4k cats & dogs" -> "4k%20cats%20%26%20dogs"
        base = f"https://xhamster.com/search/"
        url = base + path

        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency

        params = {}

        if minimum_quality:
            params["quality"] = minimum_quality

        if sort_by:
            params["sort"] = sort_by

        if category:
            params["cats"] = category

        if vr:
            params["format"] = "vr"

        if full_length_only:
            params["length"] = "full"

        if min_duration:
            params["min-duration"] = min_duration  # note: += (don’t overwrite the URL)

        if date:
            params["date"] = date

        if production:
            params["prod"] = production

        if fps:
            params["fps"] = fps

        query_string = urlencode(params, doseq=True)
        final_url = f"{url}?{query_string}" if query_string else url
        page_urls = [build_page_url(url=final_url, is_search=True, idx=page) for page in range(1, pages + 1)]
        assert isinstance(videos_concurrency, int)
        assert isinstance(pages_concurrency, int)

        async for scrape_result in self.iterator(use_alternative_constructor=True, video_link_extractor=extractor_shorts, target_page_urls=page_urls,
                                 max_video_concurrency=videos_concurrency, max_page_concurrency=pages_concurrency,
                                         on_video_error=on_video_error, on_page_error=on_page_error,
                                         keep_original_order=keep_original_order):
            yield scrape_result
