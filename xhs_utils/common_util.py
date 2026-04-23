import os
from loguru import logger
from dotenv import load_dotenv

def load_env():
    load_dotenv()
    cookies_str = os.getenv('COOKIES')
    datas_base_path = os.getenv('DATAS_BASE_PATH')
    return cookies_str, datas_base_path

def init():
    cookies_str, datas_base_path = load_env()
    if not datas_base_path:
        raise ValueError('环境变量 DATAS_BASE_PATH 未配置，请在 .env 中设置')
    datas_base_path = os.path.abspath(os.path.expanduser(datas_base_path))
    media_base_path = os.path.join(datas_base_path, 'media_datas')
    excel_base_path = os.path.join(datas_base_path, 'excel_datas')
    for base_path in [media_base_path, excel_base_path]:
        if not os.path.exists(base_path):
            os.makedirs(base_path)
            logger.info(f'创建目录 {base_path}')
    base_path = {
        'media': media_base_path,
        'excel': excel_base_path,
    }
    return cookies_str, base_path
