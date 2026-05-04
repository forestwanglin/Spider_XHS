import unittest
from unittest.mock import Mock, patch

from main import Data_Spider, parse_detail_filter, should_spider_note_detail


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

    @patch("main.save_to_db")
    def test_filtered_search_note_is_saved_to_db_without_fetching_detail(self, mock_save_to_db):
        spider = Data_Spider()
        spider.xhs_apis.search_some_note = Mock(
            return_value=(
                True,
                "ok",
                [
                    {
                        "model_type": "note",
                        "id": "note_1",
                        "xsec_token": "token_1",
                        "note_card": {
                            "type": "normal",
                            "user": {
                                "user_id": "user_1",
                                "nickname": "tester",
                                "avatar": "https://img/avatar.jpg",
                            },
                            "title": "title",
                            "desc": "desc",
                            "interact_info": {
                                "liked_count": "50",
                                "collected_count": "5",
                                "comment_count": "1",
                                "share_count": "0",
                            },
                            "image_list": [],
                            "tag_list": [],
                            "time": 1714819200000,
                            "ip_location": "Shanghai",
                        },
                    }
                ],
            )
        )

        with patch.object(spider, "spider_note") as mock_spider_note:
            note_list, success, _ = spider.spider_some_search_note(
                query="test",
                require_num=20,
                cookies_str="cookie",
                base_path={"db": {}},
                save_choice="db",
                crawl_task_id="task_1",
                detail_filter=parse_detail_filter('{"like":[100,200]}'),
            )

        self.assertTrue(success)
        self.assertEqual(note_list, [])
        mock_spider_note.assert_not_called()
        mock_save_to_db.assert_called_once()
        saved_rows = mock_save_to_db.call_args.args[0]
        self.assertEqual(len(saved_rows), 1)
        self.assertEqual(saved_rows[0]["note_id"], "note_1")
        self.assertIn('"id": "note_1"', saved_rows[0]["raw_data"])


if __name__ == "__main__":
    unittest.main()
