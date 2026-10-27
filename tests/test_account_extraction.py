"""Regressions for account lists rendered from embedded page data."""
import json
import unittest

from xhamster_api.modules.consts import extractor_videos


class AccountExtractionTests(unittest.TestCase):
    def test_liked_list_uses_account_json_and_excludes_recommendations(self):
        item = {"id": 123, "pageURL": "/videos/example-xh123", "title": "Example",
                "duration": 125, "imageURL": "https://example.test/thumb.jpg"}
        data = {"layoutPage": {"likedVideosListProps": {"videoThumbProps": [item]},
                               "trendingVideoListProps": {"videoThumbProps": [dict(item, id=456)]}}}
        html = '<script id="initials-script">window.initials=' + json.dumps(data) + ';</script>'
        rows = extractor_videos(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://xhamster.com/videos/example-xh123")
        self.assertEqual(rows[0]["duration"], "125")

    def test_empty_account_collection_does_not_return_sidebar_videos(self):
        html = '<script id="initials-script">window.initials={"favoritesVideoCollection":[]};</script>'
        html += '<div data-role="video-section-container"><div class="video-thumb" data-video-id="123">'
        html += '<a data-role="thumb-link" href="/videos/recommendation-xh123">Other video</a></div></div>'
        self.assertEqual(extractor_videos(html), [])

    def test_search_and_category_initials_extraction(self):
        v1 = {"id": 11, "pageURL": "/videos/video-11", "title": "Vid 11", "duration": 300, "thumbURL": "https://img.test/11.jpg"}
        v2 = {"id": 22, "pageURL": "/videos/video-22", "title": "Vid 22", "duration": 400, "thumbURL": "https://img.test/22.jpg"}
        short_item = {"id": 99, "pageURL": "/shorts/moment-99", "title": "Moment 99", "thumbURL": "https://img.test/99.jpg"}

        # Search result containing videos and an embedded short
        data = {"searchResult": {"videoThumbProps": [v1, short_item]}}
        html = '<script id="initials-script">window.initials=' + json.dumps(data) + ';</script>'
        rows = extractor_videos(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video_id"], "11")

        # Category page containing trending videos
        data_cat = {"pagesCategoryComponent": {"trendingVideoListProps": {"videoThumbProps": [v2]}}}
        html_cat = '<script id="initials-script">window.initials=' + json.dumps(data_cat) + ';</script>'
        rows_cat = extractor_videos(html_cat)
        self.assertEqual(len(rows_cat), 1)
        self.assertEqual(rows_cat[0]["video_id"], "22")

    def test_extractor_shorts_from_initials(self):
        from xhamster_api.modules.consts import extractor_shorts
        s1 = {"id": 88, "pageURL": "/shorts/short-88", "title": "Short 88", "thumbURL": "https://img.test/88.jpg", "views": 500}
        data = {"momentsComponent": {"videoListProps": {"videoThumbProps": [s1]}}}
        html = '<script id="initials-script">window.initials=' + json.dumps(data) + ';</script>'
        shorts = extractor_shorts(html)
        self.assertEqual(len(shorts), 1)
        self.assertEqual(shorts[0]["video_id"], "88")
        self.assertEqual(shorts[0]["title"], "Short 88")


if __name__ == "__main__":
    unittest.main()
