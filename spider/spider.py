import json
import os
import argparse
from datetime import datetime
from loguru import logger
from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.common_util import init
from xhs_utils.data_util import handle_note_info, download_note, save_to_xlsx, save_to_db, parse_count


DETAIL_FILTER_FIELDS = {
    'like': 'like',
    'collect': 'collect',
    'comment': 'comment',
}


def parse_detail_filter(detail_filter_json: str):
    if not detail_filter_json:
        return {}
    try:
        raw_filter = json.loads(detail_filter_json)
    except json.JSONDecodeError as e:
        raise ValueError(f'--detailFilter 不是合法 JSON: {e}') from e
    if not isinstance(raw_filter, dict):
        raise ValueError('--detailFilter 必须是 JSON 对象')

    detail_filter = {}
    for key, value in raw_filter.items():
        if key == 'share':
            logger.warning('列表页无法稳定拿到分享数，已忽略 detailFilter 中的分享条件')
            continue
        if key not in DETAIL_FILTER_FIELDS:
            raise ValueError(f'--detailFilter 不支持字段 {key}，仅支持 like、collect、comment')
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f'--detailFilter 字段 {key} 必须是 [最小值, 最大值]')
        min_count = parse_count(value[0])
        max_count = parse_count(value[1])
        if min_count > max_count:
            raise ValueError(f'--detailFilter 字段 {key} 的最小值不能大于最大值')
        normalized_key = DETAIL_FILTER_FIELDS[key]
        detail_filter[normalized_key] = (min_count, max_count)
    return detail_filter


def should_spider_note_detail(note: dict, detail_filter: dict):
    if not detail_filter:
        return True
    interact_info = note.get('note_card', {}).get('interact_info', {}) or {}
    count_fields = {
        'like': 'liked_count',
        'collect': 'collected_count',
        'comment': 'comment_count',
    }
    for key, (min_count, max_count) in detail_filter.items():
        count = parse_count(interact_info.get(count_fields[key]))
        if count < min_count or count > max_count:
            return False
    return True


def build_db_record_from_search_note(note: dict):
    note_url = f"https://www.xiaohongshu.com/explore/{note['id']}?xsec_token={note['xsec_token']}"
    raw_note = {
        'id': note['id'],
        'url': note_url,
        'note_card': note.get('note_card', {}),
    }
    return {
        'note_id': note['id'],
        'note_url': note_url,
        'raw_data': json.dumps(raw_note, ensure_ascii=False),
    }


class Data_Spider():
    def __init__(self):
        self.xhs_apis = XHS_Apis()

    def spider_note(self, note_url: str, cookies_str: str, proxies=None):
        """
        爬取一个笔记的信息
        :param note_url:
        :param cookies_str:
        :return:
        """
        note_info = None
        try:
            success, msg, note_info = self.xhs_apis.get_note_info(note_url, cookies_str, proxies)
            if success:
                raw_note_info = note_info['data']['items'][0]
                raw_note_info['url'] = note_url
                note_info = handle_note_info(raw_note_info)
                note_info['raw_data'] = json.dumps(raw_note_info, ensure_ascii=False)
        except Exception as e:
            success = False
            msg = e
        logger.info(f'爬取笔记信息 {note_url}: {success}, msg: {msg}')
        return success, msg, note_info

    def spider_some_note(self, notes: list, cookies_str: str, base_path: dict, save_choice: str, excel_name: str = '', crawl_task_id: str = '', proxies=None, extra_db_rows: list = None):
        """
        爬取一些笔记的信息
        :param notes:
        :param cookies_str:
        :param base_path:
        :return:
        """
        if (save_choice == 'all' or save_choice == 'excel') and excel_name == '':
            raise ValueError('excel_name 不能为空')
        note_list = []
        for note_url in notes:
            success, msg, note_info = self.spider_note(note_url, cookies_str, proxies)
            if note_info is not None and success:
                note_list.append(note_info)
        for note_info in note_list:
            if save_choice == 'all' or 'media' in save_choice:
                download_note(note_info, base_path['media'], save_choice)
        if save_choice == 'all' or save_choice == 'excel':
            file_path = os.path.abspath(os.path.join(base_path['excel'], f'{excel_name}.xlsx'))
            save_to_xlsx(note_list, file_path)
        if save_choice == 'all' or save_choice == 'db':
            db_rows = list(note_list)
            if extra_db_rows:
                db_rows.extend(extra_db_rows)
            save_to_db(db_rows, base_path['db'], crawl_task_id)


    def spider_user_all_note(self, user_url: str, cookies_str: str, base_path: dict, save_choice: str, excel_name: str = '', crawl_task_id: str = '', proxies=None):
        """
        爬取一个用户的所有笔记
        :param user_url:
        :param cookies_str:
        :param base_path:
        :return:
        """
        note_list = []
        try:
            success, msg, all_note_info = self.xhs_apis.get_user_all_notes(user_url, cookies_str, proxies)
            if success:
                logger.info(f'用户 {user_url} 作品数量: {len(all_note_info)}')
                for simple_note_info in all_note_info:
                    note_url = f"https://www.xiaohongshu.com/explore/{simple_note_info['note_id']}?xsec_token={simple_note_info['xsec_token']}"
                    note_list.append(note_url)
            if save_choice == 'all' or save_choice == 'excel':
                excel_name = user_url.split('/')[-1].split('?')[0]
            self.spider_some_note(note_list, cookies_str, base_path, save_choice, excel_name, crawl_task_id, proxies)
        except Exception as e:
            success = False
            msg = e
        logger.info(f'爬取用户所有视频 {user_url}: {success}, msg: {msg}')
        return note_list, success, msg

    def spider_some_search_note(self, query: str, require_num: int, cookies_str: str, base_path: dict, save_choice: str, sort_type_choice=0, note_type=0, note_time=0, note_range=0, pos_distance=0, geo: dict = None,  excel_name: str = '', crawl_task_id: str = '', detail_filter: dict = None, proxies=None):
        """
            指定数量搜索笔记，设置排序方式和笔记类型和笔记数量
            :param query 搜索的关键词
            :param require_num 搜索的数量
            :param cookies_str 你的cookies
            :param base_path 保存路径
            :param sort_type_choice 排序方式 0 综合排序, 1 最新, 2 最多点赞, 3 最多评论, 4 最多收藏
            :param note_type 笔记类型 0 不限, 1 视频笔记, 2 普通笔记
            :param note_time 笔记时间 0 不限, 1 一天内, 2 一周内天, 3 半年内
            :param note_range 笔记范围 0 不限, 1 已看过, 2 未看过, 3 已关注
            :param pos_distance 位置距离 0 不限, 1 同城, 2 附近 指定这个必须要指定 geo
            返回搜索的结果
        """
        note_list = []
        filtered_db_rows = []
        try:
            success, msg, notes = self.xhs_apis.search_some_note(query, require_num, cookies_str, sort_type_choice, note_type, note_time, note_range, pos_distance, geo, proxies)
            if success:
                notes = list(filter(lambda x: x['model_type'] == "note", notes))
                logger.info(f'搜索关键词 {query} 笔记数量: {len(notes)}')
                for note in notes:
                    if not should_spider_note_detail(note, detail_filter):
                        logger.info(f"跳过详情抓取 note_id={note.get('id')}，未命中 detailFilter")
                        filtered_db_rows.append(build_db_record_from_search_note(note))
                        continue
                    note_url = f"https://www.xiaohongshu.com/explore/{note['id']}?xsec_token={note['xsec_token']}"
                    note_list.append(note_url)
            if save_choice == 'all' or save_choice == 'excel':
                excel_name = query
            self.spider_some_note(note_list, cookies_str, base_path, save_choice, excel_name, crawl_task_id, proxies, extra_db_rows=filtered_db_rows)
        except Exception as e:
            success = False
            msg = e
        logger.info(f'搜索关键词 {query} 笔记: {success}, msg: {msg}')
        return note_list, success, msg

if __name__ == '__main__':
    """
        此文件为爬虫的入口文件，可以直接运行
        apis/xhs_pc_apis.py 为爬虫的api文件，包含小红书的全部数据接口，可以继续封装
        apis/xhs_creator_apis.py 为小红书创作者中心的api文件
        感谢star和follow
    """

    parser = argparse.ArgumentParser(
        description='Spider_XHS 入口',
        formatter_class=argparse.RawTextHelpFormatter,
        epilog='示例:\n'
               '  python main.py --query "榴莲"\n'
               '  python main.py --query "榴莲" --num 20 --detailFilter \'{"like":[100,999999],"collect":[20,999999],"comment":[0,999999]}\'\n'
               '说明:\n'
               '  使用 -h 或 --help 打印所有可用参数和描述。\n'
               '  列表页无法稳定拿到分享数，detailFilter 中的 share 会被忽略。'
    )
    parser.add_argument('--query', required=True, help='搜索关键词，必填')
    parser.add_argument('--num', type=int, default=20, help='搜索数量，默认 20')
    parser.add_argument('--cookie', required=False, default='', help='Cookie，可选；不传则使用 .env 中 COOKIES')
    parser.add_argument('--taskId', required=False, default='', help='任务ID，可选；不传则默认当前时间 yyyyMMdd_HHmmss')
    parser.add_argument(
        '--detailFilter',
        required=False,
        default='',
        help='详情抓取前置过滤 JSON，可选；仅支持 like/collect/comment 区间，示例: \'{"like":[100,999999],"collect":[20,999999],"comment":[0,999999]}\''
    )
    args = parser.parse_args()
    detail_filter = parse_detail_filter(args.detailFilter)

    env_cookies_str, base_path = init()
    cookies_str = args.cookie.strip() if args.cookie and args.cookie.strip() else env_cookies_str
    if not cookies_str:
        raise ValueError('Cookie 未提供：请传 --cookie 或在 .env 中配置 COOKIES')
    data_spider = Data_Spider()
    crawl_task_id = args.taskId.strip() if args.taskId and args.taskId.strip() else datetime.now().strftime('%Y%m%d_%H%M%S')
    """
        save_choice: all: 保存所有的信息（media + excel + db）, media: 保存视频和图片（media-video只下载视频, media-image只下载图片，media都下载）, excel: 保存到excel, db: 保存到mysql
        save_choice 为 excel 或者 all 时，excel_name 不能为空
    """

    # # 1 爬取列表的所有笔记信息 笔记链接 如下所示 注意此url会过期！
    # notes = [
    #     r'https://www.xiaohongshu.com/explore/683fe17f0000000023017c6a?xsec_token=ABBr_cMzallQeLyKSRdPk9fwzA0torkbT_ubuQP1ayvKA=&xsec_source=pc_user',
    # ]
    # data_spider.spider_some_note(notes, cookies_str, base_path, 'all', 'test', crawl_task_id=crawl_task_id)

    # # 2 爬取用户的所有笔记信息 用户链接 如下所示 注意此url会过期！
    # user_url = 'https://www.xiaohongshu.com/user/profile/64c3f392000000002b009e45?xsec_token=AB-GhAToFu07JwNk_AMICHnp7bSTjVz2beVIDBwSyPwvM=&xsec_source=pc_feed'
    # data_spider.spider_user_all_note(user_url, cookies_str, base_path, 'all', crawl_task_id=crawl_task_id)

    # 3 搜索指定关键词的笔记
    query = args.query
    query_num = args.num
    sort_type_choice = 0  # 0 综合排序, 1 最新, 2 最多点赞, 3 最多评论, 4 最多收藏
    note_type = 0 # 0 不限, 1 视频笔记, 2 普通笔记
    note_time = 0  # 0 不限, 1 一天内, 2 一周内天, 3 半年内
    note_range = 0  # 0 不限, 1 已看过, 2 未看过, 3 已关注
    pos_distance = 0  # 0 不限, 1 同城, 2 附近 指定这个1或2必须要指定 geo
    # geo = {
    #     # 经纬度
    #     "latitude": 39.9725,
    #     "longitude": 116.4207
    # }
    data_spider.spider_some_search_note(query, query_num, cookies_str, base_path, 'all', sort_type_choice, note_type, note_time, note_range, pos_distance, geo=None, crawl_task_id=crawl_task_id, detail_filter=detail_filter)
