from __future__ import annotations
import re
import urllib
import logging
import chompjs
import asyncio
import argparse

from xhamster_api.modules import errors as provider_errors
from base_api.modules.provider import fetch_content, download_errors, download_hls
from base_api.modules.logger import configure_app_logging, get_logger, log_context

from base_api.modules.static_functions import str_to_bool

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
    make_iterator_config,
    is_resource_gone,
    default_on_error,
    scrape_stream,
)

from xhamster_api.modules.errors import (NetworkError, UnknownNetworkError, NotFound, BotDetection, ProxyError,
                                         DownloadFailed, LoginFailed)
from xhamster_api.modules.consts import (build_page_url, headers, REGEX_AVATAR, REGEX_M3U8, extractor_videos,
                                        REGEX_THUMBNAIL, extractor_shorts)


logger = get_logger(__name__)


_is_resource_gone = is_resource_gone
on_error = default_on_error


async def get_html_content(core: BaseCore, url: str, *, owner=None) -> str:
    return await fetch_content(core, url, logger=logger, owner=owner,
                               error_types=provider_errors)


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
        html_content = await get_html_content(url=self.url, core=self.core, owner=self)
        return await asyncio.to_thread(self._extract_data, html_content)

    def _extract_data(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        url = getattr(self, "url", "")

        # Anchor check: ensure page layout is recognized
        anchor = (
            parser.css_first(".landing-info")
            or parser.css_first(".category-info")
            or parser.css_first('article[class*="-container"]')
            or parser.css_first('div[data-role$="-info"]')
        )
        if not anchor:
            logger.warning(
                "Layout anchor ('.landing-info' / '.category-info') not found for %s; page layout may have changed.",
                url,
            )

        # 1. Name
        name_node = (
            parser.css_first(".landing-info__user-title")
            or parser.css_first("[data-role='user-title']")
            or parser.css_first("[data-role='user-name']")
            or parser.css_first("h1.page-title")
            or parser.css_first("h1")
        )
        name = name_node.text(strip=True) if name_node else None
        if not name:
            logger.warning("Name not found for %s", url)

        # 2. Metrics (subscribers, videos, views)
        subscribers_count = None
        videos_count = None
        total_views_count = None

        for metric in parser.css(".landing-info__metric"):
            text_node = metric.css_first(".landing-info__metric-text")
            val_node = metric.css_first(".landing-info__metric-value")
            if not (text_node and val_node):
                continue
            text = text_node.text(strip=True).lower()
            val = val_node.text(strip=True)
            if "subscriber" in text:
                subscribers_count = val
            elif "video" in text:
                videos_count = val
            elif "view" in text:
                total_views_count = val

        # Fallback to positional metric values if text matching missed any
        metric_values = [n.text(strip=True) for n in parser.css(".landing-info__metric-value")]
        if subscribers_count is None and len(metric_values) > 0:
            subscribers_count = metric_values[0]
        if videos_count is None and len(metric_values) > 1:
            videos_count = metric_values[1]
        if total_views_count is None and len(metric_values) > 2:
            total_views_count = metric_values[2]

        if not subscribers_count:
            logger.warning("Could not extract subscribers_count for %s", url)
        if not videos_count:
            logger.warning("Could not extract videos_count for %s", url)
        if not total_views_count:
            logger.warning("Could not extract total_views_count for %s", url)

        # 3. Avatar URL
        avatar_url = None
        logo_node = parser.css_first(".landing-info__logo-image") or parser.css_first("div[class*='logo-image']")
        if logo_node:
            style = logo_node.attributes.get("style", "")
            match = re.search(r"url\(['\"]?(.*?)['\"]?\)", style)
            if match:
                avatar_url = match.group(1)
            else:
                img_node = logo_node.css_first("img")
                if img_node:
                    avatar_url = img_node.attributes.get("src")

        if not avatar_url:
            avatar_match = REGEX_AVATAR.search(html_content)
            if avatar_match:
                avatar_url = avatar_match.group(1)

        if not avatar_url:
            logger.warning("Could not extract avatar_url for %s", url)

        # 4. Personal Information (pornstar / creator)
        pornstar_info: dict[str, str] = {}
        if self._is_pornstar_or_creator:
            about_container = (
                parser.css_first('div[data-role$="-about-me"]')
                or parser.css_first('div[class*="aboutMe"]')
                or parser.css_first('div[class*="personalInfo"]')
            )
            if about_container:
                for li in about_container.css("li"):
                    label_node = li.css_first('[class*="label"]')
                    value_node = li.css_first('[class*="value"]')
                    if label_node and value_node:
                        key = label_node.text(strip=True)
                        val = value_node.text(strip=True)
                    else:
                        divs = li.css("div")
                        if len(divs) >= 2:
                            key = divs[0].text(strip=True)
                            val = divs[1].text(strip=True)
                        else:
                            continue
                    if key:
                        pornstar_info[key] = val

            if not pornstar_info:
                logger.warning("Could not extract personal information for %s", url)

        return {
            "name": name,
            "subscribers_count": subscribers_count,
            "videos_count": videos_count,
            "total_views_count": total_views_count,
            "avatar_url": avatar_url,
            "pornstar_information": pornstar_info,
        }

    _extract_html = _extract_data


    def videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        page_urls = [build_page_url(url=self.url, is_search=False, idx=page) for page in range(1, pages + 1)]
        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_videos,
            iterator_config=iterator_config,
        )

    def get_shorts(
            self,
            pages: int = 2,
            iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Short], None]:
        url = self.url

        if not url.endswith("/"):
            url += "/"

        url += "shorts"
        page_urls = [build_page_url(url, is_search=False, idx=page) for page in range(1, pages + 1)]
        return scrape_stream(
            core=self.core,
            constructor=Short,
            target_page_urls=page_urls,
            item_extractor=extractor_shorts,
            iterator_config=iterator_config,
        )


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
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
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

    @download_errors(DownloadFailed)
    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        return await download_hls(self, configuration)


@dataclass(slots=True, kw_only=True)
class Video(BaseMedia):
    core: BaseCore
    url: str
    video_id: int | None = media_field("html")
    title: str | None = media_field("html")
    rating_percentage: int | None = media_field("html")
    likes: int | None = media_field("html")
    dislikes: int | None = media_field("html")
    uploader_name: str | None = media_field("html")
    uploader_subscribers: int | None = media_field("html")
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
    created_timestamp: str | int | None = media_field("html")
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
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
        return await asyncio.to_thread(self._extract_html, html_content)

    def _extract_html(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        url = getattr(self, "url", "")

        # Anchor check: ensure this is a recognizable video page
        if (
            not parser.css_first("main.video-type-video")
            and not parser.css_first(".player-container")
            and not parser.css_first("[data-role='video-heading']")
        ):
            logger.warning(
                "Video container anchor ('main.video-type-video' / '.player-container') not found for %s; page layout may have changed.",
                url,
            )

        data: dict = {}
        script = parser.css_first("script#initials-script")
        if script and script.text():
            try:
                json_text = script.text().split("window.initials=", 1)[-1].strip().rstrip(";")
                data = chompjs.parse_js_object(json_text)
            except Exception as e:
                logger.warning("Failed to parse initials-script JSON for %s: %s", url, e, exc_info=True)

        video_entity = data.get("videoEntity", {})
        video_model = data.get("videoModel", {})
        tags_component = data.get("videoTagsComponent", {}).get("tags", [])

        # 1. Title
        title = video_entity.get("title") or video_model.get("title")
        if not title:
            title_node = parser.css_first("h1.title-3e2be, [data-role='video-heading'] h1, h1")
            title = title_node.text(strip=True) if title_node else None
        if not title:
            logger.warning("Title not found for %s", url)

        # 2. Video ID & Hash
        video_id = video_entity.get("id") or video_model.get("id")
        if video_id is not None:
            try:
                video_id = int(video_id)
            except (ValueError, TypeError):
                video_id = None
        if not video_id:
            player_el = parser.css_first(".player-container, [data-role='xplayer']")
            search_scope = player_el.html if player_el else html_content
            if id_match := re.search(r"/(\d{3})/(\d{3})/(\d{3})/", search_scope):
                try:
                    video_id = int("".join(id_match.groups()))
                except ValueError:
                    video_id = None
        if not video_id:
            logger.warning("Video ID not found for %s", url)

        video_hash = video_entity.get("idHashSlug") or video_model.get("idHashSlug")
        if not video_hash:
            if hash_match := re.search(r"-(xh[a-zA-Z0-9]+)", url):
                video_hash = hash_match.group(1)
            elif mobile_link := parser.css_first("a[href*='x_platform_switch=mobile'], a.version-cb57f"):
                if m := re.search(r"-(xh[a-zA-Z0-9]+)", mobile_link.attributes.get("href", "")):
                    video_hash = m.group(1)

        # 3. Description
        description = video_entity.get("description") or video_model.get("description")
        if description is None:
            desc_el = parser.css_first("p.controls-info__description, meta[name='description']")
            if desc_el:
                description = desc_el.attributes.get("content") if desc_el.tag == "meta" else desc_el.text(strip=True)
            else:
                description = ""

        # 4. Duration
        duration = video_entity.get("duration") or video_model.get("duration")
        if duration is not None:
            try:
                duration = int(duration)
            except (ValueError, TypeError):
                duration = 0
        else:
            eta_el = parser.css_first(".timing .eta, span.eta")
            if eta_el:
                parts = eta_el.text(strip=True).split(":")
                try:
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    else:
                        duration = 0
                except ValueError:
                    duration = 0
            else:
                duration = 0

        # 5. Views
        views = video_entity.get("views") or video_model.get("views")
        if views is not None:
            try:
                views = int(views)
            except (ValueError, TypeError):
                views = 0
        else:
            views_node = parser.css_first(".eyeIcon-a993a, [aria-label*='views']")
            if views_node and (label := views_node.attributes.get("aria-label")):
                if v_match := re.search(r"(\d+)", label.replace(" ", "")):
                    try:
                        views = int(v_match.group(1))
                    except ValueError:
                        views = 0
            if views is None:
                views = 0

        # 6. Comments count
        comments_count = video_entity.get("commentsCount") or video_model.get("comments")
        if comments_count is not None:
            try:
                comments_count = int(comments_count)
            except (ValueError, TypeError):
                comments_count = 0
        else:
            comm_el = parser.css_first(
                ".comments-control .count-c7c46, [data-role='video-comments'] .count-c7c46, span.count-c7c46"
            )
            if comm_el and comm_el.text(strip=True).isdigit():
                comments_count = int(comm_el.text(strip=True))
            else:
                comments_count = 0

        # 7. Timestamps
        created_timestamp = video_model.get("created")
        date_ago = video_entity.get("dateAgo")
        if not created_timestamp or not date_ago:
            date_node = parser.css_first(".entity-info-container__date")
            if date_node:
                created_timestamp = created_timestamp or date_node.attributes.get("data-tooltip")
                date_ago = date_ago or date_node.text(strip=True)

        # 8. Ratings
        rating_model = video_entity.get("rating", {})
        rating_percentage = rating_model.get("value")
        likes = rating_model.get("likes")
        dislikes = rating_model.get("dislikes")

        if rating_percentage is None or likes is None or dislikes is None:
            rating_info = parser.css_first("p.rb-new__info")
            if rating_info:
                if rating_percentage is None:
                    tooltip = rating_info.attributes.get("data-tooltip", "")
                    if rp_match := re.search(r"(\d+)", tooltip):
                        rating_percentage = int(rp_match.group(1))
                if likes is None or dislikes is None:
                    aria = rating_info.attributes.get("aria-label", "")
                    if ld_match := re.search(r"(\d+)\s+likes?,\s+(\d+)\s+dislikes?", aria):
                        likes = int(ld_match.group(1))
                        dislikes = int(ld_match.group(2))
                    elif split_match := re.search(r"(\d+)\s*/\s*(\d+)", rating_info.text(strip=True)):
                        likes = int(split_match.group(1))
                        dislikes = int(split_match.group(2))

        try:
            rating_percentage = int(rating_percentage) if rating_percentage is not None else 0
        except (ValueError, TypeError):
            rating_percentage = 0

        try:
            likes = int(likes) if likes is not None else 0
        except (ValueError, TypeError):
            likes = 0

        try:
            dislikes = int(dislikes) if dislikes is not None else 0
        except (ValueError, TypeError):
            dislikes = 0

        # 9. Technical Specs
        is_vr = video_entity.get("isVr", False)
        is_hd = video_model.get("isHD")
        max_resolution = video_entity.get("maxResolution")
        orientation = video_entity.get("orientation")

        if max_resolution is None:
            res_nodes = parser.css(
                ".chooser-control.xp-settings-inner-list-inner span[data-value], .quality.chooser-control span[data-value]"
            )
            for rn in res_nodes:
                val = rn.attributes.get("data-value", "").strip()
                if val and val != "auto":
                    max_resolution = val
                    break

        if is_hd is None:
            is_hd = bool(parser.css_first("span.HD")) or (
                max_resolution in ("720p", "1080p", "1440p", "2160p", "4k")
            )

        if not orientation:
            if or_node := parser.css_first("use[id='straight'], use[id='gay'], use[id='shemale']"):
                orientation = or_node.attributes.get("id")
            else:
                orientation = "straight"

        # 10. Taxonomy & Uploader
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

        if not pornstars:
            pornstars = [p.get("name") for p in video_entity.get("pornstarModels", []) if p.get("name")]

        if not categories or not tags or not pornstars:
            for a in parser.css("#video-tags-list-container a[href]"):
                href = a.attributes.get("href", "")
                if "faphouse.com" in href:
                    continue
                label_el = a.css_first("[class*='label-']")
                item_name = label_el.text(strip=True) if label_el else a.text(strip=True)
                if not item_name:
                    continue
                if "/pornstars/" in href and item_name not in pornstars:
                    pornstars.append(item_name)
                elif ("/categories/" in href or href.endswith("/hd")) and item_name not in categories:
                    categories.append(item_name)
                elif "/tags/" in href and item_name not in tags:
                    tags.append(item_name)

        if not categories:
            logger.warning("Categories not found for %s", url)
        if not tags:
            logger.warning("Tags not found for %s", url)

        if not uploader_name:
            uploader_el = parser.css_first(
                ".entity-author-container__name span, .entity-author-container__name, "
                "div.item-50dd2 span.body-bold-8643e.label-5984a.label-96c3e"
            )
            if uploader_el:
                uploader_name = uploader_el.text(strip=True)
        if not uploader_name:
            logger.warning("Uploader name not found for %s", url)

        try:
            uploader_subscribers = int(uploader_subscribers) if uploader_subscribers is not None else 0
        except (ValueError, TypeError):
            uploader_subscribers = 0

        # 11. Media Links
        thumbnail = video_model.get("thumbURL") or video_entity.get("thumbBig")
        if not thumbnail:
            preload_el = parser.css_first(".xp-preload-image")
            if preload_el and (style := preload_el.attributes.get("style")):
                if t_match := re.search(r"url\(['\"]?([^'\"()]+(?:\([^)]*\)[^'\"()]*)*)['\"]?\)", style):
                    thumbnail = t_match.group(1)
                elif t_match := re.search(r"url\(['\"]([^'\"]+)['\"]\)", style):
                    thumbnail = t_match.group(1)
        if not thumbnail:
            vid_node = parser.css_first("video.player-container__no-script-video")
            if vid_node:
                thumbnail = vid_node.attributes.get("poster")
        if not thumbnail:
            thumb_match = REGEX_THUMBNAIL.search(html_content)
            thumbnail = thumb_match.group(1) if thumb_match else ""
        if not thumbnail:
            logger.warning("Thumbnail not found for %s", url)

        preview_thumbnail = video_model.get("previewThumbURL")
        if not preview_thumbnail:
            sprite_el = parser.css_first(".thumb-image-container__sprite[data-sprite]")
            if sprite_el:
                preview_thumbnail = sprite_el.attributes.get("data-sprite")

        m3u8_base_url = ""
        m3u8_match = REGEX_M3U8.search(html_content)
        if m3u8_match:
            m3u8_base_url = m3u8_match.group(0).replace(r"\/", "/")
        elif (hls_url := data.get("xplayerSettings", {}).get("sources", {}).get("hls", {}).get("h264", {}).get("url")):
            m3u8_base_url = hls_url
        elif (fallback_vid := parser.css_first("video.player-container__no-script-video, a.player-container__no-player")):
            m3u8_base_url = fallback_vid.attributes.get("src") or fallback_vid.attributes.get("href") or ""

        if not m3u8_base_url:
            logger.warning("m3u8_base_url not found for %s", url)

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
            "m3u8_base_url": m3u8_base_url,
        }

    @download_errors(DownloadFailed)
    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        return await download_hls(self, configuration)


class Client:
    def __init__(self, core: BaseCore | None = None):
        if core is None:
            core = BaseCore(RuntimeConfig())
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

    def search_videos(self, query: str,
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

        if iterator_config is None:
            iterator_config = make_iterator_config()

        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_videos,
            iterator_config=iterator_config,
        )

    async def login(self, username: str, password: str, cookies: dict | None = None) -> Account:
        with log_context(self, "https://xhamster.com/x-api"):
            try:
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
                    message = f"Login failed at https://xhamster.com/x-api: HTTP {response.status_code}"
                    logger.error(message)
                    raise LoginFailed(message)
            except Exception:
                logger.exception("Login failed")
                raise


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="XHamster API Command Line Interface")
    parser.add_argument("--download", metavar="URL", type=str, help="URL to download from")
    parser.add_argument("--quality", metavar="best|half|worst", type=str, default="best", help="The video quality (best, half, worst)")
    parser.add_argument("--file", metavar="FILE", type=str, help="(Optional) Specify a file with URLs (separated with new lines)")
    parser.add_argument("--output", metavar="DIR", type=str, required=True, help="The output path (with filename or directory)")
    parser.add_argument("--no-title", metavar="True,False", type=str, nargs="?", const="True", default="False",
                        help="Whether to apply video title automatically to output path or not")
    return parser


async def run_main(args_list: list[str] | None = None):
    parser = create_parser()
    args = parser.parse_args(args_list)
    no_title = str_to_bool(args.no_title) if isinstance(args.no_title, str) else bool(args.no_title)
    config = DownloadConfigHLS(quality=args.quality, path=args.output, no_title=no_title)

    urls: list[str] = []
    if args.download:
        urls.append(args.download)
    if args.file:
        with open(args.file, "r") as f:
            urls.extend([line.strip() for line in f if line.strip()])

    if not urls:
        parser.print_help()
        return

    client = Client()
    for url in urls:
        print(f"Fetching video information for: {url}")
        try:
            video = await client.get_video(url, load_html=True)
            title = getattr(video, "title", None) or url
            print(f"Starting download for: {title}")
            await video.download(configuration=config)
            print(f"Download complete: {title}")
        except Exception as e:
            logger.exception("CLI failed while processing %s", url)
            print(f"Error downloading {url}: {e}")


def main():
    configure_app_logging(level=logging.INFO)
    try:
        asyncio.run(run_main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")


if __name__ == "__main__":
    main()
