import json
from backend.app.utils.filter import filter_titles

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

