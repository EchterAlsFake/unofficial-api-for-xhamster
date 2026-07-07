from __future__ import annotations
import os
import urllib
import logging
import chompjs
import asyncio

from dataclasses import dataclass, field
from urllib.parse import urlencode, quote
from curl_cffi import AsyncSession, Response
from selectolax.lexbor import LexborHTMLParser
from base_api.modules.config import RuntimeConfig
from base_api.modules.type_hints import DownloadReport
from typing import Literal, AsyncGenerator
from base_api import DownloadConfigHLS, ScrapeResult, BaseCore, Helper, BaseMedia
from base_api.modules.errors import NetworkRequestError, BotProtectionDetected, UnknownError, InvalidProxy, ResourceGone

from xhamster_api.modules.errors import (NetworkError, UnknownNetworkError, NotFound, BotDetection, ProxyError,
                                         DownloadFailed, LoginFailed)
from xhamster_api.modules.consts import (build_page_url, headers, REGEX_AVATAR, REGEX_M3U8, extractor_videos,
                                        REGEX_THUMBNAIL, extractor_shorts)
from xhamster_api.modules.type_hints import on_error_hint


logger = logging.getLogger(__name__)


async def on_error(url: str, error: Exception, attempt: int) -> bool:
    logger.error(f"URL: {url}, ERROR: {error}, Attempt: {attempt}")

    if isinstance(error, ResourceGone):
        return False

    return True

async def get_html_content(core: BaseCore, url: str) -> str | None | dict:
    logger.debug(f"Fetching HTML content for URL: {url}")
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


@dataclass(kw_only=True, slots=True)
class Something(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = None
    subscribers_count: str | None = None
    videos_count: str | None = None
    total_views_count: str | None = None
    avatar_url: str | None = None
    pornstar_creator_information: dict | None = None

    # You don't need that
    _is_pornstar_or_creator: bool = False

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._load_html())

    async def _load_html(self):
        html_content = await get_html_content(url=self.url, core=self.core)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_data, html_content)
        self.name = data.get("name")
        self.subscribers_count = data.get("subscribers_count")
        self.videos_count = data.get("videos_count")
        self.total_views_count = data.get("total_views_count")
        self.avatar_url = data.get("avatar_url")
        self.pornstar_creator_information = data.get("pornstar_information", None)

    def _extract_data(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        if self._is_pornstar_or_creator:
            name = parser.css_first("h2.h3-bold-8643e.primary-8643e.landing-info__user-title").text(strip=True)

        else:
            name = parser.css_first("h1.h3-bold-8643e.primary-8643e.landing-info__user-title").text(strip=True)

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


    async def videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False,
                     load_html: bool = False,
                     ) -> AsyncGenerator[ScrapeResult, None]:
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [build_page_url(url=self.url, is_search=False, idx=page) for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for scrape_result in helper.iterator(video_link_extractor=extractor_videos,
                                 max_video_concurrency=videos_concurrency, max_page_concurrency=pages_concurrency,
                                 on_video_error=on_video_error, on_page_error=on_page_error, target_page_urls=page_urls,
                                 keep_original_order=keep_original_order, fetch_html=load_html):
            yield scrape_result


    async def get_shorts(self, pages: int = 2, videos_concurrency: int = 2, pages_concurrency: int = 1,
                         on_video_error: on_error_hint = on_error,
                         on_page_error: on_error_hint = None,
                         keep_original_order: bool = False,
                         load_html: bool = False
                         ) -> AsyncGenerator[ScrapeResult, None]:
        url = self.url

        if not url.endswith("/"):
            url += "/"

        url += "shorts"
        page_urls = [build_page_url(url, is_search=False, idx=page) for page in range(1, pages + 1)]
        helper = Helper(core=self.core, constructor=Short)
        async for scrape_result in helper.iterator(video_link_extractor=extractor_shorts, fetch_html=load_html,
                                 target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                 max_page_concurrency=pages_concurrency, on_video_error=on_video_error,
                                 on_page_error=on_page_error, keep_original_order=keep_original_order):
            yield scrape_result


class Channel(Something):
    pass


@dataclass(kw_only=True, slots=True)
class Pornstar(Something):
    _is_pornstar_or_creator: bool = field(default=True, init=False)


@dataclass(kw_only=True, slots=True)
class Creator(Something):
    _is_pornstar_or_creator: bool = field(default=True, init=False)


class Account:
    def __init__(self, core: BaseCore):
        self.core = core

    async def get_liked_videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False,
                     load_html: bool = False,
                     ) -> AsyncGenerator[ScrapeResult, None]:
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"https://xhamster.com/my/liked/videos?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for scrape_result in helper.iterator(video_link_extractor=extractor_videos,
                                                   max_video_concurrency=videos_concurrency,
                                                   max_page_concurrency=pages_concurrency,
                                                   on_video_error=on_video_error, on_page_error=on_page_error,
                                                   target_page_urls=page_urls,
                                                   keep_original_order=keep_original_order, fetch_html=load_html):
            yield scrape_result

    async def get_account_playlist(self, url: str, pages: int = 2, videos_concurrency: int | None = None,
                               pages_concurrency: int | None = None,
                               on_video_error: on_error_hint = on_error,
                               on_page_error: on_error_hint = None,
                               keep_original_order: bool = False,
                               load_html: bool = False) -> AsyncGenerator[ScrapeResult, None]:
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for scrape_result in helper.iterator(video_link_extractor=extractor_videos,
                                                   max_video_concurrency=videos_concurrency,
                                                   max_page_concurrency=pages_concurrency,
                                                   on_video_error=on_video_error, on_page_error=on_page_error,
                                                   target_page_urls=page_urls,
                                                   keep_original_order=keep_original_order, fetch_html=load_html):
            yield scrape_result


@dataclass(kw_only=True, slots=True)
class Short(BaseMedia):
    core: BaseCore
    url: str
    title: str | None = None
    tags: list[str] | None = None
    thumbnail: str | None = None
    video_id: str | None = None
    comment_count: str | None = None
    duration: str | None = None
    created_at: str | None = None
    poster_url: str | None = None
    author_link: str | None = None
    author_logo: str | None = None
    m3u8_base_url: str | None = None
    likes: str | None = None
    views: str | None = None
    author_subscribers: str | None = None
    author: str | None = None

    # Optional
    preview_video: str | None = None


    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self) -> None:
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_data, html_content)
        self.title = data.get("title")
        self.author = data.get("author")
        self.likes = data.get("likes")
        self.views = data.get("views")
        self.comment_count = data.get("comments")
        self.duration = data.get("duration")
        self.video_id = data.get("video_id")
        self.created_at = data.get("created_at")
        self.tags = data.get("tags")
        self.author_subscribers = data.get("subscribers")
        self.author_logo = data.get("author_logo")
        self.author_link = data.get("author_link")
        self.thumbnail = data.get("thumb_url")
        self.poster_url = data.get("poster_url")
        self.m3u8_base_url = data.get("m3u8_base_url")

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
            "comments": comments,
            "duration": duration,
            "video_id": video_id,
            "created_at": created,
            "tags": tags,
            "subscribers": subscribers,
            "author_logo": author_logo,
            "author_link": author_link,
            "thumb_url": thumb_url,
            "poster_url": poster_url,
            "m3u8_base_url": m3u8_base_url
        }

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        """
        :param configuration:
        :return:
        """
        config = configuration

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
    video_id: str | None = None
    title: str | None = None
    rating_percentage: int | None = None
    likes: int | None = None
    dislikes: int | None = None
    uploader_name: str | None = None
    uploader_subscribers: str | None = None
    tags: list[str] | None = None
    categories: list[str] | None = None
    pornstars: list[str] | None = None
    thumbnail: str | None = None
    m3u8_base_url: str | None = None

    # Optional
    length: str | None = None
    preview_video: str | None = None
    views: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self) -> None:
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        self.video_id = data.get("video_id")
        self.title = data.get("title")
        self.rating_percentage = data.get("rating_percentage")
        self.likes = data.get("likes")
        self.dislikes = data.get("dislikes")
        self.uploader_name = data.get("uploader_name")
        self.uploader_subscribers = data.get("uploader_subscribers")
        self.tags = data.get("tags")
        self.categories = data.get("categories")
        self.pornstars = data.get("pornstars")
        self.thumbnail = data.get("thumbnail")
        self.m3u8_base_url = data.get("m3u8_base_url")

    @staticmethod
    def _extract_html(html_content) -> dict:
        lexbor = LexborHTMLParser(html_content)
        script = lexbor.css_first("script#initials-script").text()
        json_text = script.split("window.initials=", 1)[-1].strip().rstrip(";")
        data = chompjs.parse_js_object(json_text)
        video_id = data.get("videoTagsComponent", {}).get("videoId")
        title = None
        data_url = data.get("bannerUnderComments", {}).get("fh", {}).get("dataUrl", "")
        if data_url:
            parsed_url = urllib.parse.urlparse(data_url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            titles = query_params.get("videoTitle", [])
            if titles:
                title = urllib.parse.unquote_plus(titles[0])

        rating_percentage = data.get("ratingComponent", {}).get("ratingModel", {}).get("value", 0)
        likes = data.get("ratingComponent", {}).get("ratingModel", {}).get("likes", 0)
        dislikes = data.get("ratingComponent", {}).get("ratingModel", {}).get("dislikes", 0)
        _uploader_tag_model = {}

        _tags = data.get("videoTagsComponent", {}).get("tags", [])
        for tag in _tags:
            if tag.get("isUser"):
                _uploader_tag_model = tag

        uploader_name = _uploader_tag_model.get("name", "")

        if not uploader_name:
            uploader_name = lexbor.css_first("div.item-50dd2").css_first("span.body-bold-8643e.label-5984a.label-96c3e").text(strip=True)

        sub_model = _uploader_tag_model.get("subscriptionModel") or {}
        uploader_subscribers = sub_model.get("subscribers", 0)
        categories = [tag["name"] for tag in _tags if tag.get("isCategory") and "name" in tag]

        tags = [tag["name"] for tag in _tags if tag.get("isTag") and "name" in tag]

        container = lexbor.css_first("div[data-role='video-tags-list']")

        actor_elements = container.css('a[href*="/pornstars/"], a[href*="/creators/"]')

        pornstars = []
        for element in actor_elements:
            name = element.text(strip=True)
            pornstars.append(name)


        thumbnail = REGEX_THUMBNAIL.search(html_content).group(1)
        _url = REGEX_M3U8.search(html_content).group(0)
        m3u8_base_url = _url.replace("\\/", "/")  # Fixing escaped slashes

        return {
            "video_id": video_id,
            "title": title,
            "rating_percentage": rating_percentage,
            "likes": likes,
            "dislikes": dislikes,
            "uploader_name": uploader_name,
            "uploader_subscribers": uploader_subscribers,
            "categories": categories,
            "tags": tags,
            "pornstars": pornstars,
            "thumbnail": thumbnail,
            "m3u8_base_url": m3u8_base_url
        }

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        """
        :param configuration:
        :return:
        """
        config = configuration
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
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(headers)

    async def get_video(self, url: str, load_html: bool = True) -> Video:
        video = Video(url=url, core=self.core)
        return await video.load(html=load_html)

    async def get_pornstar(self, url: str, load_html: bool = True) -> Pornstar:
        pornstar = Pornstar(url=url, core=self.core)
        return await pornstar.load(html=load_html)

    async def get_creator(self, url: str, load_html: bool = True) -> Creator:
        creator = Creator(url=url, core=self.core)
        return await creator.load(html=load_html)

    async def get_channel(self, url: str, load_html: bool = True) -> Channel:
        channel = Channel(url=url, core=self.core)
        return await channel.load(html=load_html)

    async def get_short(self, url: str, load_html: bool = True) -> Short:
        short = Short(url=url, core=self.core)
        return await short.load(html=load_html)

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
        pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None,
                            on_video_error: on_error_hint = on_error,
                            on_page_error: on_error_hint = None,
                            keep_original_order: bool = False,
                            load_html: bool = False,
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
        helper = Helper(core=self.core, constructor=Video)
        async for scrape_result in helper.iterator(video_link_extractor=extractor_videos, target_page_urls=page_urls,
                                 max_video_concurrency=videos_concurrency, max_page_concurrency=pages_concurrency,
                                 on_video_error=on_video_error, on_page_error=on_page_error,
                                 keep_original_order=keep_original_order, fetch_html=load_html):
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

        response = await self.core.fetch(method="POST", url="https://xhamster.com/x-api", get_response=True,
                                    json_data=payload, headers=headers)
        if response.status_code == 200:
            logger.info("Login Successful!")
            return Account(core=self.core)


        else:
            logger.error("Login (probably) failed!")
            raise LoginFailed("Login probably failed, because server did not return a 200 response code, please report this / check your credentials!")
