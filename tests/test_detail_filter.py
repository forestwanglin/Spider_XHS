import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, Mock, patch

from main import (
    Data_Spider,
    build_title_filter_input,
    load_cleaning_rules_from_db,
    parse_cleaning_rule_ids,
    should_spider_note_detail,
)
from xhs_utils.data_util import save_to_db


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

    def test_cli_search_entrypoint_defaults_to_db_save_choice(self):
        source = Path("spider/spider.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "spider_some_search_note"
        ]

        self.assertEqual(len(calls), 1)
        self.assertGreaterEqual(len(calls[0].args), 5)
        self.assertEqual(calls[0].args[4].value, "db")

    def test_cli_note_url_entrypoint_uses_spider_some_note_db_save_choice(self):
        source = Path("spider/spider.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "spider_some_note"
        ]

        db_calls = [
            call
            for call in calls
            if len(call.args) >= 4
            and isinstance(call.args[3], ast.Constant)
            and call.args[3].value == "db"
        ]

        self.assertEqual(len(db_calls), 1)

    def test_cli_help_exposes_note_url_argument(self):
        result = subprocess.run(
            [sys.executable, "-m", "spider.spider", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("noteUrl", result.stdout)

    def test_cli_note_url_branch_runs_before_cleaning_rule_parse(self):
        source = Path("spider/spider.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        note_url_branch = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "note_url"
        )
        parse_call = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "parse_cleaning_rule_ids"
        )

        self.assertLess(note_url_branch.lineno, parse_call.lineno)

    def test_spider_note_reports_missing_items_as_detail_response_error(self):
        spider = Data_Spider()
        spider.xhs_apis.get_note_info = Mock(
            return_value=(True, "ok", {"success": True, "msg": "ok", "data": {"current_time": 1}})
        )

        success, msg, note_info = spider.spider_note(
            "https://www.xiaohongshu.com/explore/note_1",
            "cookie",
        )

        self.assertFalse(success)
        self.assertIn("data.items", str(msg))
        self.assertIsNone(note_info)

    @patch("main.save_to_db")
    def test_spider_some_note_returns_zero_saved_count_when_detail_fails(self, mock_save_to_db):
        spider = Data_Spider()
        with patch.object(spider, "spider_note") as mock_spider_note:
            mock_spider_note.return_value = (False, "data.items missing", None)

            saved_count = spider.spider_some_note(
                ["https://www.xiaohongshu.com/explore/note_1"],
                "cookie",
                {"db": {}},
                "db",
                crawl_task_id="task_1",
            )

        self.assertEqual(saved_count, 0)
        mock_save_to_db.assert_called_once_with([], {}, "task_1")

    def test_parse_cleaning_rule_ids_deduplicates_comma_separated_values(self):
        self.assertEqual(parse_cleaning_rule_ids(" 3,2，3,,1 "), [3, 2, 1])

    def test_title_filter_input_uses_search_display_title_when_title_missing(self):
        note = self.build_search_note()
        note["note_card"].pop("title")
        note["note_card"]["display_title"] = "搜索列表标题"

        self.assertEqual(build_title_filter_input([note]), {"note_1": "搜索列表标题"})

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
    @patch("main.logger.info")
    @patch("main.filter_titles", create=True)
    def test_ai_title_and_cleaning_rules_must_match_before_detail_crawl(self, mock_filter_titles, mock_logger_info, mock_save_to_db):
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
        log_messages = [call.args[0] for call in mock_logger_info.call_args_list]
        self.assertTrue(any("AI_TITLE_FILTER_REQUEST_BODY" in msg and '"note_1": "title"' in msg for msg in log_messages))
        self.assertTrue(any("AI_TITLE_FILTER_RESPONSE_DATA" in msg and '"input_key": "note_1"' in msg for msg in log_messages))
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
    def test_detail_failure_falls_back_to_search_record_with_snapshot_flags(self, mock_filter_titles, mock_save_to_db):
        spider = Data_Spider()
        spider.xhs_apis.search_some_note = Mock(return_value=(True, "ok", [self.build_search_note()]))
        mock_filter_titles.return_value = [{"input_key": "note_1", "total_score": 80}]

        with patch.object(spider, "spider_note") as mock_spider_note:
            mock_spider_note.return_value = (False, "detail failed", None)
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
        mock_spider_note.assert_called_once()
        mock_save_to_db.assert_called_once()
        saved_rows = mock_save_to_db.call_args.args[0]
        self.assertEqual(len(saved_rows), 1)
        self.assertEqual(saved_rows[0]["note_id"], "note_1")
        self.assertTrue(saved_rows[0]["ai_title_filter_passed"])
        self.assertTrue(saved_rows[0]["cleaning_rule_passed"])
        self.assertFalse(saved_rows[0]["detail_crawl_succeeded"])

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

    @patch("main.save_to_db")
    @patch("main.filter_titles", create=True)
    def test_search_display_title_is_sent_to_ai_filter_when_title_missing(self, mock_filter_titles, mock_save_to_db):
        spider = Data_Spider()
        note = self.build_search_note()
        note["note_card"].pop("title")
        note["note_card"]["display_title"] = "搜索列表标题"
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
        mock_filter_titles.assert_called_once_with({"note_1": "搜索列表标题"})
        mock_spider_note.assert_not_called()
        mock_save_to_db.assert_called_once()

    @patch("xhs_utils.data_util.pymysql.connect")
    def test_save_to_db_writes_snapshot_filter_and_detail_flags(self, mock_connect):
        cursor = Mock()
        connection = Mock()
        connection.cursor.return_value = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        mock_connect.return_value = connection

        save_to_db(
            [
                {
                    "note_id": "note_1",
                    "note_url": "https://www.xiaohongshu.com/explore/note_1",
                    "liked_count": "120",
                    "collected_count": "20",
                    "comment_count": "5",
                    "share_count": "1",
                    "ai_title_filter_passed": True,
                    "cleaning_rule_passed": False,
                    "detail_crawl_succeeded": False,
                }
            ],
            {"host": "127.0.0.1", "port": 3306, "user": "u", "password": "p", "database": "d"},
            crawl_task_id="task_1",
        )

        snapshot_sql, snapshot_rows = cursor.executemany.call_args_list[1].args
        self.assertIn("ai_title_filter_passed", snapshot_sql)
        self.assertIn("cleaning_rule_passed", snapshot_sql)
        self.assertIn("detail_crawl_succeeded", snapshot_sql)
        self.assertEqual(snapshot_rows[0], ("task_1", ANY, "note_1", 120, 20, 5, 1, 1, 0, 0))

    @patch("xhs_utils.data_util.pymysql.connect")
    def test_save_to_db_uses_search_display_title_from_raw_data_when_title_missing(self, mock_connect):
        cursor = Mock()
        connection = Mock()
        connection.cursor.return_value = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        mock_connect.return_value = connection

        raw_note = self.build_search_note()
        raw_note["url"] = "https://www.xiaohongshu.com/explore/note_1"
        raw_note["note_card"].pop("title")
        raw_note["note_card"]["display_title"] = "搜索列表标题"

        save_to_db(
            [
                {
                    "note_id": "note_1",
                    "note_url": "https://www.xiaohongshu.com/explore/note_1",
                    "raw_data": json.dumps(raw_note, ensure_ascii=False),
                }
            ],
            {"host": "127.0.0.1", "port": 3306, "user": "u", "password": "p", "database": "d"},
            crawl_task_id="task_1",
        )

        _, note_rows = cursor.executemany.call_args_list[0].args
        self.assertEqual(note_rows[0][7], "搜索列表标题")


if __name__ == "__main__":
    unittest.main()
