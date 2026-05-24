import json
from datetime import date, datetime, timedelta

import pymysql
from xhs_utils.data_util import parse_count


MAX_COUNT = 9999999


def parse_cleaning_rule_ids(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value).replace("，", ",").split(",")

    result = []
    seen = set()
    for item in raw_items:
        text = str(item).strip()
        if not text:
            continue
        rule_id = int(text)
        if rule_id in seen:
            continue
        seen.add(rule_id)
        result.append(rule_id)
    return result


def load_cleaning_rules_from_db(rule_ids, db_config):
    normalized_ids = parse_cleaning_rule_ids(rule_ids)
    if not normalized_ids:
        return []

    missing = [key for key in ["host", "port", "user", "password", "database"] if not db_config.get(key)]
    if missing:
        raise ValueError(f"MySQL 配置不完整，缺少: {', '.join(missing)}")

    placeholders = ", ".join(["%s"] * len(normalized_ids))
    sql = f"""
        SELECT *
        FROM data_cleaning_rule
        WHERE id IN ({placeholders})
          AND is_deleted = 0
          AND is_enabled = 1
    """
    conn = pymysql.connect(
        host=db_config["host"],
        port=int(db_config["port"]),
        user=db_config["user"],
        password=db_config["password"],
        database=db_config["database"],
        charset=db_config.get("charset", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, normalized_ids)
            rows = cursor.fetchall()
    finally:
        conn.close()

    rule_map = {int(row["id"]): _normalize_rule_row(row) for row in rows}
    missing_ids = [rule_id for rule_id in normalized_ids if rule_id not in rule_map]
    if missing_ids:
        raise ValueError(f"清洗规则不存在或未启用: {', '.join(str(item) for item in missing_ids)}")
    return [rule_map[rule_id] for rule_id in normalized_ids]


def should_spider_note_detail(note, cleaning_rules=None):
    cleaning_rules = cleaning_rules or []
    return all(_matches_cleaning_rule(note, rule) for rule in cleaning_rules)


def _normalize_rule_row(row):
    normalized = dict(row)
    for key in ("content_fields", "content_keyword_categories", "content_keywords"):
        value = normalized.get(key)
        if isinstance(value, str):
            try:
                normalized[key] = json.loads(value)
            except json.JSONDecodeError:
                normalized[key] = []
    return normalized


def _matches_cleaning_rule(note, rule):
    rule_type = rule.get("rule_type") or "interaction"
    if rule_type == "interaction":
        return _matches_interaction_rule(note, rule)
    if rule_type == "time":
        return _matches_time_rule(note, rule)
    if rule_type == "content":
        # TODO: 内容过滤需要明确字段来源和命中语义后再补充，目前不阻断详情抓取。
        return True
    return True


def _matches_interaction_rule(note, rule):
    interact_info = _get_interact_info(note)
    like_count = parse_count(interact_info.get("liked_count"))
    collect_count = parse_count(interact_info.get("collected_count"))
    comment_count = parse_count(interact_info.get("comment_count"))

    if (rule.get("interaction_match_mode") or "dimension_count") == "total":
        total = like_count + collect_count + comment_count
        return _is_in_range(
            total,
            rule.get("min_total_interactions"),
            rule.get("max_total_interactions"),
        )

    checks = [
        _is_in_range(like_count, rule.get("min_likes_count"), rule.get("max_likes_count")),
        _is_in_range(collect_count, rule.get("min_collects_count"), rule.get("max_collects_count")),
        _is_in_range(comment_count, rule.get("min_comments_count"), rule.get("max_comments_count")),
    ]
    required_count = int(rule.get("interaction_required_count") or 1)
    return sum(1 for matched in checks if matched) >= required_count


def _matches_time_rule(note, rule):
    note_date = _extract_note_date(note, rule.get("time_field"))
    if (rule.get("time_range_mode") or "fixed") == "recent_days":
        recent_days = int(rule.get("recent_days") or 0)
        if recent_days <= 0 or note_date is None:
            return False
        return date.today() - timedelta(days=recent_days) <= note_date <= date.today()

    start_date = _to_date(rule.get("published_from"))
    end_date = _to_date(rule.get("published_to"))
    if start_date and (note_date is None or note_date < start_date):
        return False
    if end_date and (note_date is None or note_date > end_date):
        return False
    return True


def _is_in_range(value, min_value, max_value):
    min_count = 0 if min_value is None else parse_count(min_value)
    max_count = MAX_COUNT if max_value is None else parse_count(max_value)
    return min_count <= value <= max_count


def _get_interact_info(note):
    return note.get("note_card", {}).get("interact_info", {}) or {}


def _extract_note_date(note, time_field=None):
    note_card = note.get("note_card", {}) or {}
    field_map = {
        "created_at": "time",
        "published_at": "time",
        "updated_at": "last_update_time",
    }
    keys = [field_map.get(time_field)] if time_field in field_map else []
    keys.extend(["time", "last_update_time"])
    for key in keys:
        if not key:
            continue
        value = note_card.get(key)
        parsed = _to_date(value)
        if parsed:
            return parsed
    return None


def _to_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10000000000 else value
        return datetime.fromtimestamp(timestamp).date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            pass
    return None
