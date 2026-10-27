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


if __name__ == "__main__":
    unittest.main()
