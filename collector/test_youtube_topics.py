import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from collector import youtube_topics as yt


class YouTubeTopicsTest(unittest.TestCase):
    def test_missing_key_is_safe_noop(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(yt, "_api_key", return_value=None):
            result = yt.collect_youtube_context(
                [{"article": "テスト", "rank": 1}], date(2026, 9, 30), Path(tmp)
            )
        self.assertFalse(result["enabled"])
        self.assertEqual(result["status"], "not_configured")
        self.assertEqual(result["checkedCount"], 0)
        self.assertEqual(result["items"], [])

    def test_checks_only_first_ten_and_keeps_embeddable_title_matches(self):
        rows = [{"article": f"Topic{i}", "rank": i} for i in range(1, 13)]
        searched = []

        def fake_search(_key, article, _latest_day):
            searched.append(article)
            i = int(article.removeprefix("Topic"))
            return [{"videoId": f"A{i:010d}", "searchSnippet": {}}]

        def fake_details(_key, video_ids):
            return {
                video_id: {
                    "snippet": {
                        "title": f"Topic{i} 最新ニュース",
                        "channelTitle": "Official News",
                        "publishedAt": "2026-09-30T12:00:00Z",
                        "thumbnails": {"high": {"url": "https://example.com/thumb.jpg"}},
                    },
                    "statistics": {"viewCount": str(i * 1000)},
                    "status": {"embeddable": True},
                }
                for i, video_id in enumerate(video_ids, 1)
            }

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(yt, "_api_key", return_value="test-key"), \
             patch.object(yt, "_search_topic", side_effect=fake_search), \
             patch.object(yt, "_video_details", side_effect=fake_details):
            result = yt.collect_youtube_context(rows, date(2026, 9, 30), Path(tmp))

        self.assertEqual(searched, [f"Topic{i}" for i in range(1, 11)])
        self.assertEqual(result["checkedCount"], 10)
        self.assertEqual(result["matchedCount"], 10)
        self.assertTrue(all(item["embeddable"] for item in result["items"]))
        self.assertTrue(all(item["thumbnail"].endswith("/hqdefault.jpg") for item in result["items"]))


    def test_cached_optional_thumbnail_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(yt, "_api_key", return_value="test-key"):
            cache = Path(tmp) / "youtube" / "2026-09-30.json"
            cache.parent.mkdir(parents=True)
            cache.write_text('{"source":"YouTube Data API v3","items":[{"videoId":"abcdefghijk","thumbnail":"https://i.ytimg.com/vi/abcdefghijk/maxresdefault.jpg"}]}')
            result = yt.collect_youtube_context([], date(2026, 9, 30), Path(tmp))
        self.assertEqual(result["items"][0]["thumbnail"], "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg")

    def test_quality_score_penalizes_clickbait(self):
        trusted = {"title": "田中希実 1500m決勝", "channelTitle": "【公式】TBS スポーツ"}
        noisy = {"title": "田中希実 衝撃の知られざる真相", "channelTitle": "芸能反応集"}
        self.assertGreater(yt._quality_score(trusted), 0)
        self.assertLess(yt._quality_score(noisy), 0)


if __name__ == "__main__":
    unittest.main()
