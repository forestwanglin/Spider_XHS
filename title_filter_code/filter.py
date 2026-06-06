import os
import json
import logging
import time
from typing import List, Dict, Any, Optional

# ========== 0. 代理设置必须在任何网络库 import 之前 ==========
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["ALL_PROXY"] = ""
os.environ["NO_PROXY"] = "*"

from .prompt import XHS_FILTER_PROMPT

# ========== 1. 日志配置 ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ========== 2. 配置常量 ==========
class Config:
    API_KEY = os.getenv("DEEPSEEK_API_KEY")
    BASE_URL = "https://api.deepseek.com"
    MODEL = "deepseek-v4-flash"
    TEMPERATURE = 0.0  # 规则执行必须 deterministic
    MAX_TOKENS = 25600
    TIMEOUT = 60  # 单次请求超时 60 秒
    MAX_RETRIES = 3  # 最大重试次数
    RETRY_DELAY = 2  # 重试间隔秒数

# ========== 3. Prompt 构建 ==========
def build_prompt(titles: List[str]) -> str:
    """将标题列表注入提示词模板"""
    if not titles:
        raise ValueError("标题列表不能为空")

    # 按原始示例格式：每行一条，无逗号
    titles_block = "\n".join(f"    {i + 1}、{t}" for i, t in enumerate(titles))
    return XHS_FILTER_PROMPT.replace("{INPUT_TITLE}", titles_block)

def call_deepseek(
        prompt: str,
        config: Config = Config
) -> Optional[str]:
    """
    调用 DeepSeek API，带重试、超时、异常处理。

    Returns:
        模型返回的 JSON 字符串，失败时返回 None
    """
    api_key = os.getenv("DEEPSEEK_API_KEY") or config.API_KEY
    if not api_key:
        logger.error("DEEPSEEK_API_KEY 未配置，跳过标题过滤")
        return None

    try:
        from openai import OpenAI, APIError, RateLimitError, APITimeoutError
    except ImportError as e:
        logger.error(f"openai 依赖未安装，跳过标题过滤: {e}")
        return None

    client = OpenAI(
        api_key=api_key,
        base_url=config.BASE_URL,
        timeout=config.TIMEOUT
    )

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            logger.info(f"第 {attempt} 次请求模型...")

            response = client.chat.completions.create(
                model=config.MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "你严格按照用户提供的规则执行，禁止主观发挥。必须输出合法 JSON 数组。"
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=config.TEMPERATURE,
                max_tokens=config.MAX_TOKENS,
                response_format={"type": "json_object"}  # 强制 JSON 输出
            )

            content = response.choices[0].message.content
            logger.info(f"请求成功，返回 {len(content)} 字符")
            return content

        except RateLimitError as e:
            logger.warning(f"触发限流: {e}")
            if attempt < config.MAX_RETRIES:
                wait = config.RETRY_DELAY * attempt
                logger.info(f"等待 {wait} 秒后重试...")
                time.sleep(wait)
            else:
                logger.error("限流重试耗尽")
                return None

        except APITimeoutError as e:
            logger.warning(f"请求超时: {e}")
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_DELAY)
            else:
                logger.error("超时重试耗尽")
                return None

        except APIError as e:
            logger.error(f"API 错误 (HTTP {e.status_code}): {e}")
            return None  # API 错误通常重试无用

        except Exception as e:
            logger.error(f"未知错误: {type(e).__name__}: {e}")
            return None


# ========== 5. JSON 解析与校验 ==========
def parse_result(titles: Dict[str, str], raw_json: str) -> List[Dict[str, Any]]:
    """
    解析并校验模型返回的 JSON，筛选总分≥30分的结果，并绑定原始输入key
    Args:
        titles: 原始输入字典 {key: 标题}
        raw_json: 模型返回的JSON字符串
    Returns:
        总分≥30分的结果列表（包含原始输入key），解析失败返回空列表
    """
    # 获取输入的所有key（保持顺序，与模型返回结果一一对应）
    title_keys = list(titles.keys())
    final_results = []

    try:
        data = json.loads(raw_json)

        # 解包可能的包裹格式
        if isinstance(data, dict) and "results" in data:
            data = data["results"]
        elif not isinstance(data, list):
            data = [data]

        # 遍历解析结果 + 字段兼容 + 分数筛选 + 绑定原始key
        for idx, item in enumerate(data):
            # 1. 统一兼容字段（原逻辑保留）
            total_score = item.get("total_score", item.get("final_total", 0))
            item["total_score"] = total_score
            item["rating"] = item.get("rating", item.get("level", "D"))
            item["blocked"] = item.get("blocked", item.get("is_blocked", False))

            # 2. 绑定【原始输入的key】（核心：与输入一一对应）
            if idx < len(title_keys):
                item["input_key"] = title_keys[idx]

            # 3. 核心筛选：只保留总分 ≥30 分的结果
            if total_score >= 30:
                final_results.append(item)

        logger.info(f"筛选完成：总分≥30分的结果共 {len(final_results)} 条")
        return final_results

    except Exception as e:
        logger.error(f"解析失败: {e}")
        return []


def filter_titles(titles: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    对标题列表进行筛选打分。

    Args:
        titles: 待筛选的标题字符串列表

    Returns:
        解析后的评分结果列表，每个元素为 Dict。
        失败时返回空列表 []。
    """
    if not titles:
        logger.error("输入标题列表为空")
        return []

    try:
        # 从每个字典中取出 "value" 字段，生成字符串列表
        title_values = list(titles.values())
    except KeyError as e:
        logger.error(f"字典缺少必要的 value 字段: {e}")
        return []

    # 构建 prompt
    try:
        prompt = build_prompt(title_values)
        logger.info(f"Prompt 构建完成，长度: {len(prompt)} 字符")
    except ValueError as e:
        logger.error(f"Prompt 构建失败: {e}")
        return []

    # 调用模型
    raw_result = call_deepseek(prompt)
    if raw_result is None:
        logger.error("模型调用失败，无结果")
        return []

    # 解析并返回
    results = parse_result(titles, raw_result)
    logger.info(f"成功解析 {len(results)} 条结果")
    return results



if __name__ == "__main__":
    input_title_example = {
        "64c3f392000000002b009e45": "建议大家都去死磕这几位大神",
        "64c3f392000000002b009e46": "每天拆解一个副业（1/365）-虚拟资料",
        "64c3f392000000002b009e47": "卖课赛道...拆解从0-1做知识付费MVP",
        "64c3f392000000002b009e48": "TED演讲稿388一份年卖6000份变现280w",
        "64c3f392000000002b009e49": "低成本变现方式，知识付费录播课"
    }

    result_json = filter_titles(input_title_example)

    # 打印结果
    print("\n" + "=" * 80)
    print("筛选打分结果 (左侧为原始输入Key)")
    print("=" * 80)
    for r in result_json:
        status = "🚫 BLOCKED" if r.get("blocked") else f"⭐ {r.get('rating', '?')} 级"
        # 核心修改：将原始input_key放在最前面展示
        key = r.get('input_key', '无Key')
        title = r.get('title', 'N/A')[:30]
        print(f"{key} | {title:<<30} | {status} | 总分: {r.get('total_score', 0)}")

    # 保存结果到文件（不变）
    with open("filter_result.json", "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)
    logger.info("结果已保存到 filter_result.json")
