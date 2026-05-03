import unittest

from main import parse_detail_filter, should_spider_note_detail


class DetailFilterTest(unittest.TestCase):
    def test_parse_detail_filter_ignores_share_and_matches_supported_counts(self):
        detail_filter = parse_detail_filter(
            '{"like":[100,200],"collect":[10,99],"comment":[0,20],"share":[1,999]}'
        )

        self.assertEqual(
            detail_filter,
            {
                "like": (100, 200),
                "collect": (10, 99),
                "comment": (0, 20),
            },
        )

        note = {
            "note_card": {
                "interact_info": {
                    "liked_count": "120",
                    "collected_count": "20",
                    "comment_count": "5",
                }
            }
        }
        self.assertTrue(should_spider_note_detail(note, detail_filter))

    def test_should_skip_note_when_any_supported_count_is_out_of_range(self):
        detail_filter = parse_detail_filter('{"like":[100,200],"comment":[0,20]}')
        note = {
            "note_card": {
                "interact_info": {
                    "liked_count": "99",
                    "comment_count": "5",
                }
            }
        }

        self.assertFalse(should_spider_note_detail(note, detail_filter))


if __name__ == "__main__":
    unittest.main()
