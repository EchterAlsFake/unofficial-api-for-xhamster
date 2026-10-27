from urllib.parse import urlsplit, urljoin
from base_api import append_url_path, replace_url_path, update_url_query
import re
import json

from selectolax.lexbor import LexborHTMLParser

REGEX_M3U8 = re.compile(r'https://[^"]*?_TPL_\.(?:h264|av1)\.mp4\.m3u8')
REGEX_AUTHOR_SHORTS = re.compile(r'"name":"(.*?)"')
REGEX_THUMBNAIL = re.compile(r'<meta property="og:image" content="(.*?)"/>')
REGEX_LENGTH = re.compile(r'<span class="eta">(.*?)</span>')
REGEX_AVATAR = re.compile(r"background-image: url\('(.*?)'\)")


REGEX_LIKES_SHORTS = re.compile(r'"likes":(.*?),"')

headers = {
    "Referer": "https://www.xhamster.com/"
}


def extractor_videos(html_content: str, base_url: str = "https://xhamster.com") -> list[dict[str, str]]:
    parser = LexborHTMLParser(html_content)
    stuff = []

    # Initials JSON: Account lists, search results, category pages, channel/creator listings.
    # Modern xHamster renders complete videoThumbProps inside window.initials while leaving
    # most DOM thumbnail cards as empty placeholder skeletons.
    script = parser.css_first("script#initials-script")
    if script is not None and "window.initials=" in script.text():
        try:
            initials = json.loads(script.text().split("window.initials=", 1)[1].strip().rstrip(";"))
        except (ValueError, TypeError):
            try:
                import chompjs
                initials = chompjs.parse_js_object(script.text().split("window.initials=", 1)[1].strip().rstrip(";"))
            except Exception:
                initials = {}
        if not isinstance(initials, dict):
            initials = {}

        layout = initials.get("layoutPage", {})
        liked = layout.get("likedVideosListProps") if isinstance(layout, dict) else None
        account_rows = None
        if isinstance(liked, dict):
            account_rows = liked.get("videoThumbProps", [])
        elif "favoritesVideoCollection" in initials:
            account_rows = initials["favoritesVideoCollection"]

        if isinstance(account_rows, list):
            # Account lists: respect strict account collection without mixing recommendations
            seen = set()
            for item in account_rows:
                if not isinstance(item, dict) or not item.get("pageURL"):
                    continue
                url = urljoin(base_url, item["pageURL"])
                if url in seen:
                    continue
                seen.add(url)
                stuff.append({
                    "url": url,
                    "video_id": str(item["id"]) if item.get("id") is not None else None,
                    "title": item.get("title"),
                    "duration": str(item["duration"]) if item.get("duration") is not None else None,
                    "thumbnail": item.get("imageURL") or item.get("thumbURL"),
                    "preview_video": item.get("trailerURL"),
                    "views": str(item["views"]) if item.get("views") is not None else None,
                })
            return stuff

        # For search, channels, creators, categories: collect all video listing rows
        candidate_lists = []
        if "searchResult" in initials and isinstance(initials["searchResult"], dict):
            candidate_lists.append(initials["searchResult"].get("videoThumbProps"))
        if isinstance(layout, dict) and "videoListProps" in layout and isinstance(layout["videoListProps"], dict):
            candidate_lists.append(layout["videoListProps"].get("videoThumbProps"))

        pages_cat = initials.get("pagesCategoryComponent")
        if isinstance(pages_cat, dict) and "trendingVideoListProps" in pages_cat and isinstance(pages_cat["trendingVideoListProps"], dict):
            candidate_lists.append(pages_cat["trendingVideoListProps"].get("videoThumbProps"))

        for comp_name in ("trendingVideoSectionComponent", "newestVideoSectionComponent", "videoListProps"):
            comp = initials.get(comp_name)
            if isinstance(comp, dict):
                if "videoListProps" in comp and isinstance(comp["videoListProps"], dict):
                    candidate_lists.append(comp["videoListProps"].get("videoThumbProps"))
                elif "videoThumbProps" in comp:
                    candidate_lists.append(comp.get("videoThumbProps"))

        seen = set()
        for row_list in candidate_lists:
            if not isinstance(row_list, list):
                continue
            for item in row_list:
                if not isinstance(item, dict) or not item.get("pageURL"):
                    continue
                page_url = item["pageURL"]
                # Skip shorts/moments that may be embedded in video listing carousels
                if "/shorts/" in page_url or "/moments/" in page_url or item.get("videoType") == "moment":
                    continue
                url = urljoin(base_url, page_url)
                if url in seen:
                    continue
                seen.add(url)
                stuff.append({
                    "url": url,
                    "video_id": str(item["id"]) if item.get("id") is not None else None,
                    "title": item.get("title"),
                    "duration": str(item["duration"]) if item.get("duration") is not None else None,
                    "thumbnail": item.get("imageURL") or item.get("thumbURL"),
                    "preview_video": item.get("trailerURL"),
                    "views": str(item["views"]) if item.get("views") is not None else None,
                })

        if stuff:
            return stuff

    # FIX 1: The site now renders MULTIPLE candidate containers on search
    # pages — an empty placeholder div[data-role="main-search-content"]
    # appears BEFORE the real one containing results. The old code used
    # css_first(), which always grabbed the empty placeholder and returned
    # zero items. Collect ALL matches across every known selector instead.
    containers: list = []
    for selector in (
        'div[data-role="video-section-content-role"]',
        "div.tabsAndLists-d9218",
        'div[data-role="favorites-video-collections"]',
        'div[data-role="video-section-container"]',
        'div[data-role="main-search-content"]',
    ):
        containers.extend(parser.css(selector))

    # Dedupe guard: overlapping containers could yield the same video twice.
    seen_ids = set()
    for videos in containers:
        _videos = videos.css(".video-thumb[data-video-id]")

        for video in _videos:
            video_id = video.attributes.get("data-video-id")
            if not video_id or video_id in seen_ids:
                continue

            a_tag = video.css_first('a[data-role="thumb-link"], a.thumb-image-container, a')
            if a_tag:
                url = a_tag.attributes.get("href")
                preview_video = a_tag.attributes.get("data-previewvideo")
                title = a_tag.attributes.get("aria-label") or a_tag.attributes.get("title")
            else:
                url = preview_video = title = None

            if not isinstance(url, str) or not url:
                continue

            # Skip shorts in DOM video listing
            if "/shorts/" in url or "/moments/" in url or "video-thumb__moment" in video.attributes.get("class", ""):
                continue

            seen_ids.add(video_id)

            if not title:
                title_node = video.css_first('a[title], [class*="title-"]')
                if title_node:
                    title = title_node.attributes.get("title") or title_node.text(strip=True)

            length_el = video.css_first('[data-role="video-duration"], span.eta')
            length = length_el.text(strip=True) if length_el else "N/A"

            img_tag = video.css_first('img[data-role="thumb-preview-img"], img')
            thumbnail = None
            if img_tag:
                thumbnail = img_tag.attributes.get("src") or img_tag.attributes.get("srcset") or img_tag.attributes.get("data-src")

            views_el = video.css_first("div.video-thumb-views")
            views = views_el.text(strip=True) if views_el else "0 views"

            stuff.append({
                "title": title,
                "duration": length,
                "video_id": video_id,
                "url": urljoin(base_url, url),
                "preview_video": preview_video,
                "thumbnail": thumbnail,
                "views": views
            })

    return stuff


def extractor_shorts(html_content: str, base_url: str = "https://xhamster.com") -> list[dict[str, str]]:
    parser = LexborHTMLParser(html_content)
    stuff = []
    seen = set()

    # 1. Try initials script
    script = parser.css_first("script#initials-script")
    if script is not None and "window.initials=" in script.text():
        try:
            initials = json.loads(script.text().split("window.initials=", 1)[1].strip().rstrip(";"))
        except (ValueError, TypeError):
            try:
                import chompjs
                initials = chompjs.parse_js_object(script.text().split("window.initials=", 1)[1].strip().rstrip(";"))
            except Exception:
                initials = {}

        if isinstance(initials, dict):
            candidate_lists = []
            mc = initials.get("momentsComponent")
            if isinstance(mc, dict) and "videoListProps" in mc and isinstance(mc["videoListProps"], dict):
                candidate_lists.append(mc["videoListProps"].get("videoThumbProps"))

            lp = initials.get("layoutPage")
            if isinstance(lp, dict):
                mlp = lp.get("momentsListingProps")
                if isinstance(mlp, dict) and "videoListProps" in mlp and isinstance(mlp["videoListProps"], dict):
                    candidate_lists.append(mlp["videoListProps"].get("videoThumbProps"))

            mlc = initials.get("momentsListComponent")
            if isinstance(mlc, dict):
                candidate_lists.append(mlc.get("videoThumbProps"))

            # Fallback search for any videoThumbProps inside initials
            if not candidate_lists:
                def find_thumbs(obj):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k == "videoThumbProps" and isinstance(v, list):
                                candidate_lists.append(v)
                            elif isinstance(v, (dict, list)):
                                find_thumbs(v)
                    elif isinstance(obj, list):
                        for it in obj:
                            if isinstance(it, (dict, list)):
                                find_thumbs(it)
                find_thumbs(initials)

            for rows in candidate_lists:
                if not isinstance(rows, list):
                    continue
                for item in rows:
                    if not isinstance(item, dict) or not item.get("pageURL"):
                        continue
                    url = urljoin(base_url, item["pageURL"])
                    if url in seen:
                        continue
                    seen.add(url)
                    stuff.append({
                        "title": item.get("title"),
                        "video_id": str(item["id"]) if item.get("id") is not None else None,
                        "url": url,
                        "preview_video": item.get("trailerURL"),
                        "thumbnail": item.get("imageURL") or item.get("thumbURL"),
                        "views": str(item["views"]) if item.get("views") is not None else "0",
                    })

            if stuff:
                return stuff

    # 2. DOM fallback
    for item in parser.css(".video-thumb.video-thumb__moment, .video-thumb[data-video-type='moment'], .video-thumb"):
        vid = item.attributes.get("data-video-id")
        a_tag = item.css_first("a[data-role='thumb-link'], a.thumb-image-container--moment, a")
        if not a_tag:
            continue
        href = a_tag.attributes.get("href")
        if not href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)

        title_el = item.css_first("a[title], [class*='title-']")
        title = (title_el.attributes.get("title") or title_el.text(strip=True)) if title_el else None
        if not title:
            title = a_tag.attributes.get("aria-label") or a_tag.attributes.get("title")

        img_el = item.css_first("img")
        thumb = None
        if img_el:
            thumb = img_el.attributes.get("src") or img_el.attributes.get("srcset") or img_el.attributes.get("data-src")

        views_el = item.css_first(".video-thumb-views")
        views = views_el.text(strip=True) if views_el else "0 views"

        stuff.append({
            "title": title,
            "video_id": vid,
            "url": url,
            "preview_video": a_tag.attributes.get("data-previewvideo"),
            "thumbnail": thumb,
            "views": views
        })

    return stuff


def build_page_url(url: str, is_search: bool, idx: int) -> str:
    if is_search:
        return update_url_query(url, page=idx)
    parts = urlsplit(url).path.rstrip("/").split("/")
    if len(parts) > 3 and parts[-1].isdigit():
        parts.pop()
    base_url = update_url_query(replace_url_path(url, "/".join(parts)), page=None)
    return base_url if idx == 1 else append_url_path(base_url, idx)
