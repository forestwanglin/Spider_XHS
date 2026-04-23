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
