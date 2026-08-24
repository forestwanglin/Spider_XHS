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

CREATE TABLE IF NOT EXISTS crawl_client (
  id BIGINT NOT NULL AUTO_INCREMENT,
  client_id VARCHAR(64) NOT NULL,
  callback_url VARCHAR(1024) NOT NULL,
  api_key_hash CHAR(64) NOT NULL,
  webhook_secret_ciphertext BLOB NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_crawl_client_id (client_id)
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

CREATE TABLE IF NOT EXISTS crawl_job (
  id BIGINT NOT NULL AUTO_INCREMENT,
  job_id VARCHAR(36) NOT NULL,
  client_id VARCHAR(64) NOT NULL,
  client_task_id VARCHAR(128) NOT NULL,
  idempotency_key VARCHAR(128) NOT NULL,
  crawl_type VARCHAR(64) NOT NULL,
  parameters_json JSON NOT NULL,
  credential_ciphertext BLOB,
  status VARCHAR(32) NOT NULL,
  result_cursor VARCHAR(64),
  lease_until DATETIME,
  attempt_count INT NOT NULL DEFAULT 0,
  error_message VARCHAR(1024),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME,
  completed_at DATETIME,
  PRIMARY KEY (id),
  UNIQUE KEY uk_crawl_job_id (job_id),
  UNIQUE KEY uk_crawl_job_client_idempotency (client_id, idempotency_key),
  KEY idx_crawl_job_status_lease (status, lease_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS crawl_job_delivery (
  id BIGINT NOT NULL AUTO_INCREMENT,
  event_id VARCHAR(36) NOT NULL,
  job_id VARCHAR(36) NOT NULL,
  status VARCHAR(32) NOT NULL,
  attempt_count INT NOT NULL DEFAULT 0,
  next_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  delivered_at DATETIME,
  last_error VARCHAR(1024),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_crawl_job_delivery_event (event_id),
  KEY idx_crawl_job_delivery_pending (status, next_attempt_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS crawl_job_attempt (
  id BIGINT NOT NULL AUTO_INCREMENT,
  job_id VARCHAR(36) NOT NULL,
  attempt_number INT NOT NULL,
  status VARCHAR(32) NOT NULL,
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME,
  error_message VARCHAR(1024),
  PRIMARY KEY (id),
  UNIQUE KEY uk_crawl_job_attempt (job_id, attempt_number),
  KEY idx_crawl_job_attempt_job (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
