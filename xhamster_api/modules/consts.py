import re

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


def extractor_videos(html_content: str) -> list[dict[str, str]]:
    parser = LexborHTMLParser(html_content)
    stuff = []

    videos = parser.css_first('div[data-role="video-section-content-role"]')
    if not videos:
        videos = parser.css_first("div.tabsAndLists-d9218")

    if not videos:
        videos = parser.css_first('div[data-role="favorites-video-collections"]')

    if not videos:
        videos = parser.css_first('div[data-role="video-section-container"]')

    for video in videos.css("div.video-thumb"):
        video_id = video.attributes.get("data-video-id")

        # 1. Extract Video Metadata from the <a> tag
        a_tag = video.css_first('a[data-role="thumb-link"]')
        if a_tag:
            url = a_tag.attributes.get("href")
            preview_video = a_tag.attributes.get("data-previewvideo")
            title = a_tag.attributes.get("aria-label")
        else:
            url = preview_video = title = None

        if not isinstance(url, str) or not url:
            continue

        # 2. Extract Length/Duration safely
        length_el = video.css_first('[data-role="video-duration"]')
        length = length_el.text(strip=True) if length_el else "N/A"


        # 3. Extract Thumbnail
        img_tag = video.css_first('img[data-role="thumb-preview-img"]')
        thumbnail = img_tag.attributes.get("src") if img_tag else None

        # 4. Extract Views (Falls back to looking inside the metadata container)
        views_el = video.css_first("div.video-thumb-views")
        views = views_el.text(strip=True) if views_el else "0 views"

        # Append the structured data
        stuff.append({
            "title": title,
            "length": length,
            "video_id": video_id,
            "url": url,
            "preview_video": preview_video,
            "thumbnail": thumbnail,
            "views": views
        })

    return stuff

def extractor_shorts(html_content: str) -> list[dict[str, str]]:
    parser = LexborHTMLParser(html_content)
    stuff = []

    videos = parser.css_first('div[data-role="video-section-container"]')
    for video in videos.css("div.item-74fdf.thumb-list__item.video-thumb.video-thumb__moment.thumb-list__item--can-view"):
        video_id = video.attributes.get("data-video-id")

        a_tag = video.css_first("a")
        url = a_tag.attributes.get("href")
        if not isinstance(url, str) or not url:
            continue
        preview_video = a_tag.attributes.get("data-previewvideo")

        img_tag = video.css_first("img")
        thumbnail = img_tag.attributes.get("src")

        title = video.css_first("a[title]").attributes.get("title")
        views = video.css_first("div.video-thumb-views").text(strip=True)

        stuff.append({
            "title": title,
            "video_id": video_id,
            "url": url,
            "preview_video": preview_video,
            "thumbnail": thumbnail,
            "views": views
        })
    return stuff


def build_page_url(url: str, is_search: bool, idx: int) -> str:
    if is_search:
        # query-string pagination
        joiner = "&" if "?" in url else "?"
        return f"{url}{joiner}page={idx}"

    if idx == 1:
        return url

    return f"{url}/{idx}"
