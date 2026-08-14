from __future__ import annotations
import os
import copy
import urllib
import logging
import chompjs
import asyncio

from urllib.parse import urlencode, quote
from typing import ClassVar, Literal, AsyncGenerator
from curl_cffi import AsyncSession
from selectolax.lexbor import LexborHTMLParser
from dataclasses import dataclass, field
from base_api.modules.config import IteratorConfig, RuntimeConfig
from base_api.modules.type_hints import DownloadReport
from base_api import (
    BaseCore,
    BaseMedia,
    DownloadConfigHLS,
    ErrorAction,
    ErrorMode,
    Helper,
    MediaLoadError,
    MediaLoadErrors,
    RetryPolicy,
    ScrapeErrorContext,
    ScrapeResult,
    media_field,
)
from base_api.modules.errors import (
    BotProtectionDetected,
    HTTPStatusError,
    InvalidProxy,
    NetworkRequestError,
    ResourceGone,
    UnknownError,
)

from xhamster_api.modules.errors import (NetworkError, UnknownNetworkError, NotFound, BotDetection, ProxyError,
                                         DownloadFailed, LoginFailed)
from xhamster_api.modules.consts import (build_page_url, headers, REGEX_AVATAR, REGEX_M3U8, extractor_videos,
                                        REGEX_THUMBNAIL, extractor_shorts)


logger = logging.getLogger("Xhamster API")
logger.addHandler(logging.NullHandler())


def make_iterator_config(
    *,
    max_item_concurrency: int | None = None,
    max_page_concurrency: int | None = None,
) -> IteratorConfig:
    return IteratorConfig(
        max_item_concurrency=max_item_concurrency,
        max_page_concurrency=max_page_concurrency,
        load_specific_sources=("html",),
        item_retry=None,
        page_retry=None,
        page_error_mode=ErrorMode.SKIP,
        item_error_handler=None,
        page_error_handler=None,
    )


def _is_resource_gone(error: BaseException) -> bool:
    if isinstance(error, ResourceGone):
        return True
    if isinstance(error, MediaLoadError):
        return _is_resource_gone(error.original_error)
    if isinstance(error, MediaLoadErrors):
        return any(_is_resource_gone(nested) for nested in error.errors)
    return False


async def on_error(context: ScrapeErrorContext) -> ErrorAction:
    logger.error(
        "URL: %s, ERROR: %s, Attempt: %s/%s",
        context.url,
        context.error,
        context.attempt,
        context.max_attempts,
    )

    if _is_resource_gone(context.error):
        return ErrorAction.SKIP

    return ErrorAction.RETRY


async def get_html_content(core: BaseCore, url: str) -> str:
    logger.debug(f"Fetching HTML content for URL: {url}")
    try:
        return await core.fetch_text(url)

    except HTTPStatusError as e:
        if e.status_code == 404:
            raise NotFound(f"Server returned 404 for: {url}") from e
        raise

    except NetworkRequestError as e:
        raise NetworkError(str(e)) from e

    except InvalidProxy as e:
        raise ProxyError(str(e)) from e

    except BotProtectionDetected as e:
        raise BotDetection(str(e)) from e

    except UnknownError as e:
        raise UnknownNetworkError(str(e)) from e


@dataclass(kw_only=True, slots=True)
class Something(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = media_field("html")
    subscribers_count: str | None = media_field("html")
    videos_count: str | None = media_field("html")
    total_views_count: str | None = media_field("html")
    avatar_url: str | None = media_field("html")
    pornstar_information: dict | None = media_field("html")

    # You don't need that
    _is_pornstar_or_creator: bool = False

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(url=self.url, core=self.core)
        return await asyncio.to_thread(self._extract_data, html_content)

    def _extract_data(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        if self._is_pornstar_or_creator:
            name = parser.css_first("h2.h3-bold-8643e.primary-8643e.landing-info__user-title").text(strip=True)

        else:
            name = parser.css_first("p.h3-bold-8643e.primary-8643e.landing-info__user-title").text(strip=True)

        subscribers_count = parser.css_first("div.body-8643e.primary-8643e.landing-info__metric-value").text(strip=True)
        videos_count = parser.css("div.body-8643e.primary-8643e.landing-info__metric-value")[1].text(strip=True)
        total_views_count =  parser.css("div.body-8643e.primary-8643e.landing-info__metric-value")[2].text(strip=True)
        avatar_url = REGEX_AVATAR.search(html_content).group(1)
        dictionary = {}

        if self._is_pornstar_or_creator:
            container = parser.css_first("div.personalInfo-5360e")
            if container:
                li_tags = container.css("li")
                fortnite = parser.css("ul.list-b51e4")
                if len(fortnite) > 1:
                    li_tags.extend(fortnite[1].css("li"))

                for li_tag in li_tags:
                    divs = li_tag.css("div")
                    if len(divs) >= 2:
                        key = divs[0].text(strip=True)
                        value = divs[1].text(strip=True)
                        dictionary[key] = value

        return {
            "name": name,
            "subscribers_count": subscribers_count,
            "videos_count": videos_count,
            "total_views_count": total_views_count,
            "avatar_url": avatar_url,
            "pornstar_information": dictionary
        }


    async def videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [build_page_url(url=self.url, is_search=False, idx=page) for page in range(1, pages + 1)]
        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            item_extractor=extractor_videos,
            target_page_urls=page_urls,
            iterator_config=iterator_config,
        )
        async with stream:
            async for scrape_result in stream:
                yield scrape_result


class Channel(Something):
    pass


@dataclass(kw_only=True, slots=True)
class Pornstar(Something):
    _is_pornstar_or_creator: bool = field(default=True, init=False)

    async def get_shorts(
            self,
            pages: int = 2,
            iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Short], None]:
        url = self.url

        if not url.endswith("/"):
            url += "/"

        url += "shorts"
        page_urls = [build_page_url(url, is_search=False, idx=page) for page in range(1, pages + 1)]
        helper = Helper(core=self.core, constructor=Short)

        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            item_extractor=extractor_shorts,
            target_page_urls=page_urls,
            iterator_config=iterator_config,
        )
        async with stream:
            async for scrape_result in stream:
                yield scrape_result


@dataclass(kw_only=True, slots=True)
class Creator(Something):
    _is_pornstar_or_creator: bool = field(default=True, init=False)

    async def get_shorts(
            self,
            pages: int = 2,
            iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Short], None]:
        url = self.url

        if not url.endswith("/"):
            url += "/"

        url += "shorts"
        page_urls = [build_page_url(url, is_search=False, idx=page) for page in range(1, pages + 1)]
        helper = Helper(core=self.core, constructor=Short)

        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            item_extractor=extractor_shorts,
            target_page_urls=page_urls,
            iterator_config=iterator_config,
        )
        async with stream:
            async for scrape_result in stream:
                yield scrape_result


class Account:
    def __init__(self, core: BaseCore):
        self.core = core

    async def get_liked_videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"https://xhamster.com/my/liked/videos?page={page}" for page in range(1, pages + 1)]
        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            item_extractor=extractor_videos,
            target_page_urls=page_urls,
            iterator_config=iterator_config,
        )
        async with stream:
            async for scrape_result in stream:
                yield scrape_result

    async def get_account_playlist(
        self,
        url: str,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            item_extractor=extractor_videos,
            target_page_urls=page_urls,
            iterator_config=iterator_config,
        )
        async with stream:
            async for scrape_result in stream:
                yield scrape_result


@dataclass(kw_only=True, slots=True)
class Short(BaseMedia):
    core: BaseCore
    url: str
    title: str | None = media_field("html")
    tags: list[str] | None = media_field("html")
    thumbnail: str | None = media_field("html")
    video_id: str | None = media_field("html")
    comment_count: str | None = media_field("html")
    duration: str | None = media_field("html")
    created_at: str | None = media_field("html")
    poster_url: str | None = media_field("html")
    author_link: str | None = media_field("html")
    author_logo: str | None = media_field("html")
    m3u8_base_url: str | None = media_field("html")
    likes: str | None = media_field("html")
    views: str | None = media_field("html")
    author_subscribers: str | None = media_field("html")
    author: str | None = media_field("html")

    # Optional
    preview_video: str | None = None

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_data, html_content)

    @staticmethod
    def _extract_data(html_content: str) -> dict:
        lexbor = LexborHTMLParser(html_content)
        script = lexbor.css_first("script#initials-script").text()
        # Extract the JSON part after 'window.initials='
        json_text = script.split("window.initials=", 1)[-1].strip().rstrip(";")
        data = chompjs.parse_js_object(json_text)
        title = data.get('layoutPage', {}).get('momentProps', {}).get('title', '')
        author = data.get('layoutPage', {}).get('momentProps', {}).get('landing', {}).get('name')
        likes = data.get('layoutPage', {}).get('momentProps', {}).get('ratingModel', {}).get('likes')
        views = data.get('layoutPage', {}).get('momentProps', {}).get('views')
        comments = data.get('layoutPage', {}).get('momentProps', {}).get('comments')
        duration = data.get('xplayerSettings', {}).get('duration')
        video_id = data.get('xplayerSettings', {}).get('videoId')
        if not video_id:
             video_id = data.get('layoutPage', {}).get('momentProps', {}).get('id')

        created = data.get('layoutPage', {}).get('momentProps', {}).get('created')
        tags = data.get('layoutPage', {}).get('momentProps', {}).get('tags', [])
        subscribers = data.get('layoutPage', {}).get('momentProps', {}).get('landing', {}).get('subscribers')
        author_logo = data.get('layoutPage', {}).get('momentProps', {}).get('landing', {}).get('logo', '')
        author_link = data.get('layoutPage', {}).get('momentProps', {}).get('landing', {}).get('link', '')
        thumb_url = data.get('layoutPage', {}).get('momentProps', {}).get('thumbUrl', '')
        poster_url = data.get('layoutPage', {}).get('momentProps', {}).get('posterUrl', '')
        m3u8_base_url = data.get('xplayerSettings', {}).get('sources', {}).get('hls', {}).get('h264', {}).get('url')
        if not m3u8_base_url:
            m3u8_base_url = data.get('layoutPage', {}).get('momentProps', {}).get('sources', {}).get('hls', {}).get('h264', {}).get('url')

        return {
            "title": title,
            "author": author,
            "likes": likes,
            "views": views,
            "comment_count": comments,
            "duration": duration,
            "video_id": video_id,
            "created_at": created,
            "tags": tags,
            "author_subscribers": subscribers,
            "author_logo": author_logo,
            "author_link": author_link,
            "thumbnail": thumb_url,
            "poster_url": poster_url,
            "m3u8_base_url": m3u8_base_url
        }

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        """
        :param configuration:
        :return:
        """
        await self.load_fields("title", "m3u8_base_url")
        config = copy.deepcopy(configuration)

        if not config.no_title:
            config.path = os.path.join(config.path, f"{self.title}.mp4")

        config.m3u8_base_url = self.m3u8_base_url

        try:
            logger.info(f"Starting download for Short: {self.title}")
            return await self.core.download(configuration=config)

        except Exception as e:
            raise DownloadFailed(str(e))


@dataclass(slots=True, kw_only=True)
class Video(BaseMedia):
    core: BaseCore
    url: str
    video_id: str | None = media_field("html")
    title: str | None = media_field("html")
    rating_percentage: int | None = media_field("html")
    likes: int | None = media_field("html")
    dislikes: int | None = media_field("html")
    uploader_name: str | None = media_field("html")
    uploader_subscribers: str | None = media_field("html")
    tags: list[str] | None = media_field("html")
    categories: list[str] | None = media_field("html")
    pornstars: list[str] | None = media_field("html")
    thumbnail: str | None = media_field("html")
    m3u8_base_url: str | None = media_field("html")
    video_hash: str | None = media_field("html")
    description: str | None = media_field("html")
    duration: int | None = media_field("html")
    views: int | None = media_field("html")
    comments_count: int | None = media_field("html")
    created_timestamp: str | None = media_field("html")
    date_ago: str | None = media_field("html")
    is_vr: bool | None = media_field("html")
    is_hd: bool | None = media_field("html")
    max_resolution: str | None = media_field("html")
    orientation: str | None = media_field("html")
    preview_thumbnail: str | None = media_field("html")

    # Optional
    preview_video: str | None = None

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_html, html_content)

    @staticmethod
    def _extract_html(html_content) -> dict:
        lexbor = LexborHTMLParser(html_content)
        script = lexbor.css_first("script#initials-script")

        if not script:
            return {}

        json_text = script.text().split("window.initials=", 1)[-1].strip().rstrip(";")
        data = chompjs.parse_js_object(json_text)

        # Set up base dictionary paths
        video_entity = data.get("videoEntity", {})
        video_model = data.get("videoModel", {})
        tags_component = data.get("videoTagsComponent", {}).get("tags", [])

        # 1. Core Identity
        video_id = video_entity.get("id") or video_model.get("id")
        video_hash = video_entity.get("idHashSlug") or video_model.get("idHashSlug")
        title = video_entity.get("title") or video_model.get("title")
        description = video_entity.get("description") or video_model.get("description")

        # 2. Metadata & Metrics
        duration = video_entity.get("duration") or video_model.get("duration", 0)
        views = video_entity.get("views") or video_model.get("views", 0)
        comments_count = video_entity.get("commentsCount") or video_model.get("comments", 0)
        created_timestamp = video_model.get("created")
        date_ago = video_entity.get("dateAgo")

        # 3. Ratings
        rating_model = video_entity.get("rating", {})
        rating_percentage = rating_model.get("value", 0)
        likes = rating_model.get("likes", 0)
        dislikes = rating_model.get("dislikes", 0)

        # 4. Technical Specs
        is_vr = video_entity.get("isVr", False)
        is_hd = video_model.get("isHD", False)
        max_resolution = video_entity.get("maxResolution")
        orientation = video_entity.get("orientation")  # e.g., 'straight', 'gay'

        # 5. Taxonomy loop
        categories = []
        tags = []
        pornstars = []
        uploader_name = video_model.get("author", {}).get("name")
        uploader_subscribers = 0

        for tag in tags_component:
            tag_name = tag.get("name")
            if not tag_name:
                continue

            if tag.get("isCategory"):
                categories.append(tag_name)
            elif tag.get("isTag"):
                tags.append(tag_name)
            elif tag.get("isPornstar"):
                pornstars.append(tag_name)
            elif tag.get("isUser") or tag.get("isChannel"):
                if not uploader_name:
                    uploader_name = tag_name

                sub_model = tag.get("subscriptionModel") or {}
                if "subscribers" in sub_model:
                    uploader_subscribers = sub_model["subscribers"]

        # Fallbacks for arrays/uploader
        if not pornstars:
            pornstars = [p.get("name") for p in video_entity.get("pornstarModels", []) if p.get("name")]

        if not uploader_name:
            uploader_elem = lexbor.css_first("div.item-50dd2 span.body-bold-8643e.label-5984a.label-96c3e")
            if uploader_elem:
                uploader_name = uploader_elem.text(strip=True)

        # 6. Media Links
        thumbnail = video_model.get("thumbURL") or video_entity.get("thumbBig")
        if not thumbnail:
            thumb_match = REGEX_THUMBNAIL.search(html_content)
            thumbnail = thumb_match.group(1) if thumb_match else ""

        # Often a sprite/GIF preview URL, highly useful for front-end clients
        preview_thumbnail = video_model.get("previewThumbURL")

        m3u8_base_url = ""
        m3u8_match = REGEX_M3U8.search(html_content)
        if m3u8_match:
            m3u8_base_url = m3u8_match.group(0).replace("\\/", "/")

        return {
            "video_id": video_id,
            "video_hash": video_hash,
            "title": title,
            "description": description,
            "duration": duration,
            "views": views,
            "comments_count": comments_count,
            "created_timestamp": created_timestamp,
            "date_ago": date_ago,
            "rating_percentage": rating_percentage,
            "likes": likes,
            "dislikes": dislikes,
            "is_vr": is_vr,
            "is_hd": is_hd,
            "max_resolution": max_resolution,
            "orientation": orientation,
            "uploader_name": uploader_name,
            "uploader_subscribers": uploader_subscribers,
            "categories": categories,
            "tags": tags,
            "pornstars": pornstars,
            "thumbnail": thumbnail,
            "preview_thumbnail": preview_thumbnail,
            "m3u8_base_url": m3u8_base_url
        }

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        """
        :param configuration:
        :return:
        """
        await self.load_fields("title", "m3u8_base_url")
        config = copy.deepcopy(configuration)
        if not config.no_title:
            config.path = os.path.join(config.path, f"{self.title}.mp4")

        config.m3u8_base_url = self.m3u8_base_url

        try:
            logger.info(f"Starting download for Video: {self.title}")
            return await self.core.download(configuration=config)

        except Exception as e:
            raise DownloadFailed(str(e))


class Client:
    def __init__(self, core: BaseCore = BaseCore(RuntimeConfig())):
        self.core = core
        self.account = None
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(headers)

    async def get_video(self, url: str, load_html: bool = True) -> Video:
        video = Video(url=url, core=self.core)
        if load_html:
            await video.load_sources("html")
        return video

    async def get_pornstar(self, url: str, load_html: bool = True) -> Pornstar:
        pornstar = Pornstar(url=url, core=self.core)
        if load_html:
            await pornstar.load_sources("html")
        return pornstar

    async def get_creator(self, url: str, load_html: bool = True) -> Creator:
        creator = Creator(url=url, core=self.core)
        if load_html:
            await creator.load_sources("html")
        return creator

    async def get_channel(self, url: str, load_html: bool = True) -> Channel:
        channel = Channel(url=url, core=self.core)
        if load_html:
            await channel.load_sources("html")
        return channel

    async def get_short(self, url: str, load_html: bool = True) -> Short:
        short = Short(url=url, core=self.core)
        if load_html:
            await short.load_sources("html")
        return short

    async def search_videos(self, query: str,
        minimum_quality: Literal["720p", "1080p", "2160p"] = "720p",
        sort_by: Literal["views", "newest", "best", "longest"] | None = None, # Empty string sorts by relevance

        category: Literal["german", "amateur", "18-year-old", "granny", "anal", "old-young", "mature",
        "mom", "milf", "big-tits", "big-natural-tits", "lesbian", "teen", "cum-in-mouth", "bdsm",
        "porn-for-women", "russian", "vintage", "hairy", "brutal-sex"] | list[str] | None = None ,
        vr: bool = False,
        full_length_only: bool = False,
        min_duration: Literal["2", "5", "10", "30", "40"] | None = None,
        date: Literal["latest", "weekly", "monthly", "yearly"] | None = None,
        production: Literal["studios", "creators"] | None = None,
        fps: Literal["30", "60"] | None = None,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
                            ) -> AsyncGenerator[ScrapeResult[Video], None]:
        path = quote(str(query), safe="")  # e.g. "4k cats & dogs" -> "4k%20cats%20%26%20dogs"
        base = f"https://xhamster.com/search/"
        url = base + path

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
        helper = Helper(core=self.core, constructor=Video)

        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            item_extractor=extractor_videos,
            target_page_urls=page_urls,
            iterator_config=iterator_config,
        )
        async with stream:
            async for scrape_result in stream:
                yield scrape_result

    async def login(self, username: str, password: str, cookies: dict | None = None) -> Account:
        if cookies:
            self.core.session.cookies.update(cookies)
            return Account(self.core)

        payload = [
            {
                "name": "authorizedUserModelSync",
                "requestData": {
                    "model": {
                        "id": None,
                        "$id": "c1a902b0-cb96-4098-89f9-2bd0010586aa",
                        "modelName": "authorizedUserModel",
                        "itemState": "unchanged"
                    },
                    "username": username,
                    "password": password,
                    "remember": 1,
                    "redirectURL": "https://xhamster.com/login",
                    "pageType": None,
                    "source": None,
                    "isSubscribedToUpdates": None,
                    "trusted": True
                }
            }
        ]

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",  # Tells the server this is an AJAX/API fetch
            "Origin": "https://xhamster.com",
            "Referer": "https://xhamster.com/login",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        response = await self.core.request(
            method="POST",
            url="https://xhamster.com/x-api",
            json_data=payload,
            headers=headers,
        )
        if response.status_code == 200:
            logger.info("Login Successful!")
            self.account = Account(core=self.core)
            return Account(core=self.core)

        else:
            logger.error("Login (probably) failed!")
            raise LoginFailed("Login probably failed, because server did not return a 200 response code, please report this / check your credentials!")
