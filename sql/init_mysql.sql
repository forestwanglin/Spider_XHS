CREATE DATABASE IF NOT EXISTS spider_xhs
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE spider_xhs;

CREATE TABLE IF NOT EXISTS spider_xhs_note (
  id BIGINT NOT NULL AUTO_INCREMENT,
  note_id VARCHAR(64) NOT NULL,
  note_url VARCHAR(1024),
  note_type VARCHAR(32),
  user_id VARCHAR(64),
  home_url VARCHAR(1024),
  nickname VARCHAR(255),
  avatar VARCHAR(1024),
  title VARCHAR(512),
  `desc` TEXT,
  liked_count INT DEFAULT 0,
  collected_count INT DEFAULT 0,
  comment_count INT DEFAULT 0,
  share_count INT DEFAULT 0,
  video_cover VARCHAR(1024),
  video_addr VARCHAR(1024),
  image_list JSON,
  tags JSON,
  raw_data JSON,
  upload_time VARCHAR(32),
  last_update_time VARCHAR(64),
  ip_location VARCHAR(128),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME,
  PRIMARY KEY (id),
  UNIQUE KEY uk_note_id (note_id),
  KEY idx_user_id (user_id),
  KEY idx_upload_time (upload_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS spider_xhs_note_snapshot (
  id BIGINT NOT NULL AUTO_INCREMENT,
  crawl_task_id VARCHAR(64) NOT NULL,
  crawl_time DATETIME NOT NULL,
  note_id VARCHAR(64) NOT NULL,
  liked_count INT DEFAULT 0,
  collected_count INT DEFAULT 0,
  comment_count INT DEFAULT 0,
  share_count INT DEFAULT 0,
  ai_title_filter_passed TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否通过AI标题过滤',
  cleaning_rule_passed TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否通过清洗规则',
  detail_crawl_succeeded TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否详情抓取成功',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_crawl_task_id (crawl_task_id),
  KEY idx_note_id (note_id),
  KEY idx_crawl_time (crawl_time),
  KEY idx_xhs_note_snapshot_task_flags (
    crawl_task_id,
    ai_title_filter_passed,
    cleaning_rule_passed,
    detail_crawl_succeeded
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
