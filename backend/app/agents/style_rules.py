"""去 AI 味规则集（阶段 5）。

集中维护"疲劳词表 / 禁用句式 / 正向指引"，供写手与修订 Agent 共享，
并提供轻量本地 ai_flavor 打分（不调 LLM）。
"""
import re

# 被过度使用、容易暴露 AI 味的高频词/短语
FATIGUE_WORDS: list[str] = [
    "仿佛", "彷佛", "似乎", "好像", "一丝", "一抹", "一缕", "不禁", "不由得",
    "嘴角", "眼神", "深吸一口气", "心中一紧", "心头一震", "空气仿佛凝固",
    "时间仿佛静止", "微微", "轻轻", "缓缓", "渐渐", "终于明白", "这一刻",
    "他知道", "她知道", "无法言喻", "难以名状", "五味杂陈", "百感交集",
    "不容置疑", "毋庸置疑", "宛如", "犹如", "如同",
]

# 易出现的 AI 套路句式（正则）
CLICHE_PATTERNS: list[str] = [
    r"不是[^，。]{1,12}而是[^，。]{1,12}",   # 万能排比"不是…而是…"
    r"这一刻[，,][^。]{0,20}(明白|懂得|意识到)",  # 解释性顿悟收尾
    r"(他|她|它)?(终于|这才)(明白|懂得|意识到|理解)了",
    r"空气[^。]{0,6}凝固",
    r"时间[^。]{0,6}(静止|停滞)",
]

ANTI_AI_GUIDELINES = """
【去 AI 味要求（务必遵守）】
- 避免高频套话与情绪标签词，如"仿佛/似乎/不禁/嘴角/眼神/心中一紧/空气仿佛凝固/这一刻他明白了"等；用具体动作、细节、对话替代直白的情绪说明。
- 禁用万能句式"不是……而是……"、解释性顿悟收尾（"这一刻他终于明白了……"）、段末空洞总结。
- 句子长短错落，避免连续相同节奏与排比堆砌；少用比喻连发（"仿佛……如同……宛如……"）。
- 多留白、少说教；让读者自行体会，不替人物把情绪说尽。
"""


def ai_flavor_score(text: str) -> dict:
    """对文本做轻量 AI 味打分（0–100，越高越"AI"），返回 {score, hits}。"""
    if not text:
        return {"score": 0, "hits": []}

    length = max(len(text), 1)
    hits: list[str] = []

    fatigue_count = 0
    for w in FATIGUE_WORDS:
        c = text.count(w)
        if c:
            fatigue_count += c
            hits.append(f"{w}×{c}")

    cliche_count = 0
    for pat in CLICHE_PATTERNS:
        found = re.findall(pat, text)
        if found:
            cliche_count += len(found)
            hits.append(f"套路句式×{len(found)}")

    # 每千字疲劳词密度（×6 权重）+ 套路句式（每处 ×8），裁剪到 0–100
    density = fatigue_count / length * 1000
    score = int(min(100, density * 6 + cliche_count * 8))
    return {"score": score, "hits": hits}
