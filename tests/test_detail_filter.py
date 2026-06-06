import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from main import (
    Data_Spider,
    load_cleaning_rules_from_db,
    parse_cleaning_rule_ids,
    should_spider_note_detail,
)


class DetailFilterTest(unittest.TestCase):
    def build_search_note(
        self,
        note_id="note_1",
        title="title",
        liked_count="120",
        collected_count="20",
        comment_count="5",
    ):
        return {
            "model_type": "note",
            "id": note_id,
            "xsec_token": f"token_{note_id}",
            "note_card": {
                "type": "normal",
                "user": {
                    "user_id": "user_1",
                    "nickname": "tester",
                    "avatar": "https://img/avatar.jpg",
                },
                "title": title,
                "desc": "desc",
                "interact_info": {
                    "liked_count": liked_count,
                    "collected_count": collected_count,
                    "comment_count": comment_count,
                    "share_count": "0",
                },
                "image_list": [],
                "tag_list": [],
                "time": 1714819200000,
                "ip_location": "Shanghai",
            },
        }

    def test_cli_help_only_exposes_cleaning_rule_filter(self):
        result = subprocess.run(
            [sys.executable, "-m", "spider.spider", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertNotIn("detail" + "Filter", result.stdout)
        self.assertIn("cleaningRuleIds", result.stdout)

    def test_parse_cleaning_rule_ids_deduplicates_comma_separated_values(self):
        self.assertEqual(parse_cleaning_rule_ids(" 3,2，3,,1 "), [3, 2, 1])

    @patch("xhs_utils.cleaning_rule_filter.pymysql.connect")
    def test_load_cleaning_rules_from_db_keeps_requested_order(self, mock_connect):
        cursor = Mock()
        cursor.fetchall.return_value = [
            {"id": 2, "rule_type": "interaction", "is_enabled": 1, "is_deleted": 0},
            {"id": 1, "rule_type": "content", "content_keywords": '["a"]', "is_enabled": 1, "is_deleted": 0},
        ]
        mock_connect.return_value.cursor.return_value.__enter__.return_value = cursor

        rules = load_cleaning_rules_from_db(
            [1, 2],
            {"host": "127.0.0.1", "port": 3306, "user": "u", "password": "p", "database": "d"},
        )

        self.assertEqual([rule["id"] for rule in rules], [1, 2])
        self.assertEqual(rules[0]["content_keywords"], ["a"])

    def test_cleaning_rules_require_all_rules_to_match_before_detail_crawl(self):
        note = {
            "note_card": {
                "interact_info": {
                    "liked_count": "120",
                    "collected_count": "20",
                    "comment_count": "5",
                }
            }
        }

        self.assertTrue(
            should_spider_note_detail(
                note,
                cleaning_rules=[
                    {
                        "rule_type": "interaction",
                        "interaction_match_mode": "dimension_count",
                        "min_likes_count": 100,
                        "max_likes_count": 200,
                        "interaction_required_count": 1,
                    },
                    {
                        "rule_type": "interaction",
                        "interaction_match_mode": "total",
                        "min_total_interactions": 100,
                        "max_total_interactions": 200,
                    },
                ],
            )
        )
        self.assertFalse(
            should_spider_note_detail(
                note,
                cleaning_rules=[
                    {
                        "rule_type": "interaction",
                        "interaction_match_mode": "dimension_count",
                        "min_likes_count": 100,
                        "max_likes_count": 200,
                        "interaction_required_count": 1,
                    },
                    {
                        "rule_type": "interaction",
                        "interaction_match_mode": "total",
                        "min_total_interactions": 200,
                    },
                ],
            )
        )

    @patch("main.save_to_db")
    @patch("main.filter_titles", create=True)
    def test_ai_title_and_cleaning_rules_must_match_before_detail_crawl(self, mock_filter_titles, mock_save_to_db):
        spider = Data_Spider()
        spider.xhs_apis.search_some_note = Mock(return_value=(True, "ok", [self.build_search_note()]))
        mock_filter_titles.return_value = [{"input_key": "note_1", "total_score": 80}]
        with patch.object(spider, "spider_note") as mock_spider_note:
            mock_spider_note.return_value = (True, "ok", {"note_id": "note_1"})
            note_list, success, _ = spider.spider_some_search_note(
                query="test",
                require_num=20,
                cookies_str="cookie",
                base_path={"db": {}},
                save_choice="db",
                crawl_task_id="task_1",
                cleaning_rules=[
                    {
                        "rule_type": "interaction",
                        "interaction_match_mode": "dimension_count",
                        "min_likes_count": 100,
                        "max_likes_count": 200,
                        "interaction_required_count": 3,
                    }
                ],
            )

        self.assertTrue(success)
        self.assertEqual(
            note_list,
            ["https://www.xiaohongshu.com/explore/note_1?xsec_token=token_note_1"],
        )
        mock_filter_titles.assert_called_once_with({"note_1": "title"})
        mock_spider_note.assert_called_once()
        mock_save_to_db.assert_called_once()

    @patch("main.save_to_db")
    @patch("main.filter_titles", create=True)
    def test_ai_filtered_search_note_is_saved_to_db_without_fetching_detail(self, mock_filter_titles, mock_save_to_db):
        spider = Data_Spider()
        spider.xhs_apis.search_some_note = Mock(return_value=(True, "ok", [self.build_search_note()]))
        mock_filter_titles.return_value = []

        with patch.object(spider, "spider_note") as mock_spider_note:
            note_list, success, _ = spider.spider_some_search_note(
                query="test",
                require_num=20,
                cookies_str="cookie",
                base_path={"db": {}},
                save_choice="db",
                crawl_task_id="task_1",
            )

        self.assertTrue(success)
        self.assertEqual(note_list, [])
        mock_filter_titles.assert_called_once_with({"note_1": "title"})
        mock_spider_note.assert_not_called()
        mock_save_to_db.assert_called_once()
        saved_rows = mock_save_to_db.call_args.args[0]
        self.assertEqual(len(saved_rows), 1)
        self.assertEqual(saved_rows[0]["note_id"], "note_1")
        self.assertIn('"id": "note_1"', saved_rows[0]["raw_data"])

    @patch("main.save_to_db")
    @patch("main.filter_titles", create=True)
    def test_cleaning_rule_filtered_search_note_is_saved_to_db_without_fetching_detail(self, mock_filter_titles, mock_save_to_db):
        spider = Data_Spider()
        spider.xhs_apis.search_some_note = Mock(return_value=(True, "ok", [self.build_search_note(liked_count="50")]))
        mock_filter_titles.return_value = [{"input_key": "note_1", "total_score": 80}]

        with patch.object(spider, "spider_note") as mock_spider_note:
            note_list, success, _ = spider.spider_some_search_note(
                query="test",
                require_num=20,
                cookies_str="cookie",
                base_path={"db": {}},
                save_choice="db",
                crawl_task_id="task_1",
                cleaning_rules=[
                    {
                        "rule_type": "interaction",
                        "interaction_match_mode": "dimension_count",
                        "min_likes_count": 100,
                        "max_likes_count": 200,
                        "interaction_required_count": 3,
                    }
                ],
            )

        self.assertTrue(success)
        self.assertEqual(note_list, [])
        mock_filter_titles.assert_called_once_with({"note_1": "title"})
        mock_spider_note.assert_not_called()
        mock_save_to_db.assert_called_once()
        saved_rows = mock_save_to_db.call_args.args[0]
        self.assertEqual(len(saved_rows), 1)
        self.assertEqual(saved_rows[0]["note_id"], "note_1")
        self.assertIn('"id": "note_1"', saved_rows[0]["raw_data"])

    @patch("main.save_to_db")
    @patch("main.filter_titles", create=True)
    def test_ai_filter_exception_skips_detail_without_failing_batch(self, mock_filter_titles, mock_save_to_db):
        spider = Data_Spider()
        spider.xhs_apis.search_some_note = Mock(return_value=(True, "ok", [self.build_search_note()]))
        mock_filter_titles.side_effect = RuntimeError("model unavailable")

        with patch.object(spider, "spider_note") as mock_spider_note:
            note_list, success, _ = spider.spider_some_search_note(
                query="test",
                require_num=20,
                cookies_str="cookie",
                base_path={"db": {}},
                save_choice="db",
                crawl_task_id="task_1",
            )

        self.assertTrue(success)
        self.assertEqual(note_list, [])
        mock_filter_titles.assert_called_once_with({"note_1": "title"})
        mock_spider_note.assert_not_called()
        mock_save_to_db.assert_called_once()

    @patch("main.save_to_db")
    @patch("main.filter_titles", create=True)
    def test_missing_title_is_sent_to_ai_filter_as_empty_string(self, mock_filter_titles, mock_save_to_db):
        spider = Data_Spider()
        note = self.build_search_note()
        note["note_card"].pop("title")
        spider.xhs_apis.search_some_note = Mock(return_value=(True, "ok", [note]))
        mock_filter_titles.return_value = []

        with patch.object(spider, "spider_note") as mock_spider_note:
            note_list, success, _ = spider.spider_some_search_note(
                query="test",
                require_num=20,
                cookies_str="cookie",
                base_path={"db": {}},
                save_choice="db",
                crawl_task_id="task_1",
            )

        self.assertTrue(success)
        self.assertEqual(note_list, [])
        mock_filter_titles.assert_called_once_with({"note_1": ""})
        mock_spider_note.assert_not_called()
        mock_save_to_db.assert_called_once()


if __name__ == "__main__":
    unittest.main()
