# dev 分支相对 master 的功能差异

本文档以当前 Git 提交图中的 `master...dev` 为比较基准，仅记录 `dev` 比
`master` 额外提供的功能。`dev` 已合入 `master` 的上游鉴权与请求层更新；本
文不重复描述这些共同能力。

## 1. 命令行直链抓取

`dev` 将 `spider/spider.py` 从示例式入口扩展为可传参的命令行入口：

```bash
python -m spider.spider --noteUrl 'https://www.xiaohongshu.com/explore/<note-id>?xsec_token=...'
```

- `--noteUrl` 可重复传入，支持一次直接抓取多篇笔记。
- 直接抓取使用 `media-db` 保存策略：下载媒体并写入数据库。
- `--taskId` 可指定抓取批次标识；未提供时自动生成时间格式的任务 ID。

## 2. Cookie 校验与抓取参数

新增或扩展的命令行参数：

| 参数 | 用途 |
| --- | --- |
| `--validate-cookies --cookies <cookie>` | 仅校验显式提供的 Cookie 是否有效。 |
| `--cookies <cookie>` | 覆盖 `.env` 中的 `COOKIES`。 |
| `--num <n>` | 指定搜索抓取数量，默认 20。 |
| `--taskId <id>` | 指定数据库快照使用的抓取任务 ID。 |
| `--cleaning-rules-file <path>` | 指定 JSON 清洗规则文件；不传或 `[]` 表示不过滤。 |

## 3. 清洗规则过滤

`xhs_utils/cleaning_rule_filter.py` 通过 JSON 文件驱动详情抓取过滤：

- 使用 `--cleaning-rules-file <path>` 传入 JSON 规则数组；未传或空数组不启用过滤。
- 不再解析规则 ID，也不从 MySQL 读取 `data_cleaning_rule`。
- 根据规则判断搜索结果是否需要继续抓取详情。
- 未通过规则的笔记不会请求详情，但仍会保存可追溯的原始搜索信息和过滤结果。

## 4. AI 标题过滤

新增 `title_filter_code/`：

- 批量构造笔记 ID 到标题的映射并调用 OpenAI 兼容接口进行筛选。
- AI 服务不可用时按全部通过处理，避免服务故障阻塞常规抓取。
- AI 调用异常时跳过本批详情抓取，并记录失败原因。
- 保存 `ai_title_filter_passed`、`cleaning_rule_passed` 和
  `detail_crawl_succeeded` 三个状态，区分被过滤与详情抓取失败。

## 5. MySQL 持久化与抓取快照

新增 MySQL 保存能力和初始化脚本 `sql/init_mysql.sql`。

默认数据库为 `spider_xhs`，主要表如下：

| 表 | 用途 |
| --- | --- |
| `spider_xhs_note` | 笔记详情、原始数据、作者信息、媒体地址和最新指标。 |
| `spider_xhs_note_snapshot` | 按 `crawl_task_id` 记录每次抓取的互动指标与过滤/详情状态。 |

支持的保存策略：

| 策略 | 行为 |
| --- | --- |
| `db` | 仅写 MySQL。 |
| `media-db` | 下载媒体并写 MySQL。 |
| `all` | 下载媒体、导出 Excel 并写 MySQL。 |

数据库连接读取 `.env` 中的 `DATABASE_URL`，仅连接独立 `spider_xhs` 库。

## 6. 媒体与数据保存改进

- 详情抓取成功时保留 `raw_data`，便于后续重新解析或审计。
- 直链抓取和搜索抓取均可记录详情抓取是否成功。
- 保存数据库时对必填 MySQL 配置进行校验，并使用批量插入更新笔记与快照。

## 7. 依赖与测试

`dev` 额外引入：

- `PyMySQL`：MySQL 持久化。
- `openai`：AI 标题过滤。

新增 `tests/test_detail_filter.py`，覆盖清洗规则加载、标题过滤、详情跳过和
数据库记录构造等场景。

## 8. 关键文件

- `spider/spider.py`
- `xhs_utils/cleaning_rule_filter.py`
- `xhs_utils/data_util.py`
- `title_filter_code/`
- `sql/init_mysql.sql`
- `tests/test_detail_filter.py`
