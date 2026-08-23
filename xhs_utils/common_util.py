import os
import time
import random
import hashlib
import binascii

from loguru import logger
from dotenv import load_dotenv

_A1_CHARSET = 'abcdefghijklmnopqrstuvwxyz1234567890'


def load_env():
    load_dotenv()
    cookies_str = os.getenv('COOKIES')
    datas_base_path = os.getenv('DATAS_BASE_PATH')
    db_config = {
        'host': os.getenv('MYSQL_HOST', '127.0.0.1'),
        'port': int(os.getenv('MYSQL_PORT', '3306')),
        'user': os.getenv('MYSQL_USER', ''),
        'password': os.getenv('MYSQL_PASSWORD', ''),
        'database': os.getenv('MYSQL_DATABASE', ''),
        'charset': os.getenv('MYSQL_CHARSET', 'utf8mb4'),
    }
    return cookies_str, datas_base_path, db_config


def init():
    cookies_str, datas_base_path, db_config = load_env()
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
        'db': db_config,
    }
    return cookies_str, base_path


def generate_a1():
    ts_hex = hex(int(time.time() * 1000))[2:]
    random_str = ''.join(random.choices(_A1_CHARSET, k=30))
    a_part = ts_hex + random_str + '5' + '0' + '000'
    crc = binascii.crc32(a_part.encode()) & 0xFFFFFFFF
    return (a_part + str(crc))[:52]


def generate_web_id(a1):
    return hashlib.md5(a1.encode()).hexdigest()
