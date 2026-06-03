"""本地文风统计指纹。

不依赖 LLM：用于把参考文本的句长、段落、对白、标点和高频表达转成
可展示、可注入写作 prompt 的稳定约束。
"""
from collections import Counter
import re

from app.agents.style_rules import FATIGUE_WORDS


_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_QUOTE_RE = re.compile(r"[“「『](.*?)[”」』]", re.S)
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?]+")
_SENTENCE_KEEP_RE = re.compile(r"[^。！？!?]+[。！？!?]?")
_PUNCTUATION_GROUPS = [
    ("逗号", "，,"),
    ("句号", "。"),
    ("顿号", "、"),
    ("问号", "？?"),
    ("感叹号", "！!"),
    ("省略号", "…"),
    ("分号", "；;"),
    ("冒号", "：:"),
    ("破折号", "—"),
    ("引号", "“”「」『』\""),
]

_STOP_TERMS = {
    "一个", "一种", "这个", "那个", "这些", "那些", "他们", "她们", "我们", "你们",
    "自己", "什么", "没有", "只是", "可以", "已经", "不是", "因为", "所以", "但是",
    "如果", "还是", "还有", "这里", "那里", "一样", "时候", "开始", "然后", "突然",
    "进行", "成为", "看到", "听到", "知道", "觉得", "不能", "不会", "需要", "正在",
}

_SAMPLE_KIND_LABELS = {
    "dialogue": "对白",
    "action": "动作",
    "atmosphere": "场景",
    "interior": "心理",
    "narration": "叙述",
}

_ACTION_TERMS = "冲 跑 追 挡 退 跨 抬 按 抓 推 撞 斩 劈 落 站 转 停 走 穿 伸 握".split()
_ATMOSPHERE_TERMS = "风 雨 雪 雾 光 影 夜 天空 城市 校园 街道 看台 操场 声音 安静 黑暗".split()
_INTERIOR_TERMS = "心 想 记得 明白 意识 害怕 犹豫 沉默 呼吸 掌心 眼前".split()


def _visible_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _ratio(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(float(part) / float(total) * 100, 1)


def _paragraphs(text: str) -> list[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    blocks = [p.strip() for p in re.split(r"\n\s*\n+", normalized) if p.strip()]
    if len(blocks) > 1:
        return blocks
    return [p.strip() for p in normalized.split("\n") if p.strip()]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text or "") if _visible_len(s) >= 2]


def _sentences_keep(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_KEEP_RE.findall(text or "") if _visible_len(s) >= 8]


def _clean_sample(text: str, limit: int = 320) -> str:
    sample = re.sub(r"\s+", " ", text or "").strip()
    if _visible_len(sample) <= limit:
        return sample
    out = ""
    for sentence in _sentences_keep(sample):
        if _visible_len(out + sentence) > limit:
            break
        out = f"{out}{sentence}"
    return out.strip() or sample[:limit].strip()


def _sample_kind(text: str) -> str:
    if any(mark in text for mark in "“”「」『』\""):
        return "dialogue"
    if sum(1 for term in _ACTION_TERMS if term in text) >= 2:
        return "action"
    if sum(1 for term in _ATMOSPHERE_TERMS if term in text) >= 2:
        return "atmosphere"
    if sum(1 for term in _INTERIOR_TERMS if term in text) >= 2:
        return "interior"
    return "narration"


def _sample_score(text: str) -> float:
    length = _visible_len(text)
    score = 100.0 - abs(length - 180) * 0.25
    score += min(20, len(re.findall(r"[，。！？；：、]", text)))
    if any(mark in text for mark in "“”「」『』\""):
        score += 8
    if "\n" in text:
        score += 4
    return score


def extract_style_samples(text: str, max_samples: int = 6) -> list[dict]:
    candidates: list[tuple[float, str, str]] = []
    for paragraph in _paragraphs(text):
        clean = _clean_sample(paragraph)
        length = _visible_len(clean)
        if 45 <= length <= 360:
            candidates.append((_sample_score(clean), _sample_kind(clean), clean))

    sentence_chunks = _sentences_keep(text)
    for index in range(0, len(sentence_chunks), 2):
        clean = _clean_sample("".join(sentence_chunks[index:index + 2]), limit=240)
        length = _visible_len(clean)
        if 45 <= length <= 260:
            candidates.append((_sample_score(clean) - 5, _sample_kind(clean), clean))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict] = []
    seen_texts: set[str] = set()
    preferred_order = ["dialogue", "action", "atmosphere", "interior", "narration"]
    for kind in preferred_order:
        for _, candidate_kind, clean in candidates:
            compact = re.sub(r"\W+", "", clean)
            if candidate_kind != kind or compact in seen_texts:
                continue
            selected.append(
                {
                    "kind": kind,
                    "label": _SAMPLE_KIND_LABELS.get(kind, kind),
                    "text": clean,
                    "char_count": _visible_len(clean),
                }
            )
            seen_texts.add(compact)
            break
        if len(selected) >= max_samples:
            break

    for _, kind, clean in candidates:
        if len(selected) >= max_samples:
            break
        compact = re.sub(r"\W+", "", clean)
        if compact in seen_texts:
            continue
        selected.append(
            {
                "kind": kind,
                "label": _SAMPLE_KIND_LABELS.get(kind, kind),
                "text": clean,
                "char_count": _visible_len(clean),
            }
        )
        seen_texts.add(compact)
    return selected[:max_samples]


def _term_candidates(text: str) -> list[str]:
    terms: list[str] = []
    for run in _CJK_RE.findall(text or ""):
        if len(run) <= 1:
            continue
        if 2 <= len(run) <= 5 and run not in _STOP_TERMS:
            terms.append(run)
            continue
        for size in (3, 2):
            for index in range(0, max(0, len(run) - size + 1)):
                term = run[index:index + size]
                if term not in _STOP_TERMS:
                    terms.append(term)
    latin_terms = [item.lower() for item in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text or "")]
    return terms + latin_terms


def analyze_style_stats(text: str) -> dict:
    sample_chars = _visible_len(text)
    paragraphs = _paragraphs(text)
    paragraph_lengths = [_visible_len(item) for item in paragraphs]
    sentences = _sentences(text)
    sentence_lengths = [_visible_len(item) for item in sentences]
    sentence_count = len(sentence_lengths)

    short_count = len([length for length in sentence_lengths if length <= 18])
    medium_count = len([length for length in sentence_lengths if 18 < length <= 35])
    long_count = len([length for length in sentence_lengths if length > 35])

    dialogue_chars = sum(_visible_len(match) for match in _QUOTE_RE.findall(text or ""))
    dialogue_sentence_count = len([sentence for sentence in sentences if any(mark in sentence for mark in "“”「」『』\"")])

    punctuation = []
    for label, chars in _PUNCTUATION_GROUPS:
        count = sum((text or "").count(ch) for ch in chars)
        if count:
            punctuation.append(
                {
                    "mark": label,
                    "count": count,
                    "per_1000_chars": round(count / max(sample_chars, 1) * 1000, 1),
                }
            )
    punctuation.sort(key=lambda item: item["per_1000_chars"], reverse=True)

    term_counts = Counter(_term_candidates(text))
    top_terms = [
        {"term": term, "count": count}
        for term, count in term_counts.most_common(18)
        if count > 1
    ][:12]
    overuse_floor = max(4, int(sample_chars / 900))
    overused_terms = [item for item in top_terms if item["count"] >= overuse_floor][:8]
    fatigue_terms = [
        {"term": word, "count": count}
        for word in FATIGUE_WORDS
        if (count := (text or "").count(word)) > 0
    ][:10]

    stats = {
        "sample_chars": sample_chars,
        "paragraph_count": len(paragraphs),
        "sentence_count": sentence_count,
        "avg_sentence_chars": round(sum(sentence_lengths) / sentence_count, 1) if sentence_count else 0.0,
        "avg_paragraph_chars": round(sum(paragraph_lengths) / len(paragraph_lengths), 1) if paragraph_lengths else 0.0,
        "short_sentence_ratio": _ratio(short_count, sentence_count),
        "medium_sentence_ratio": _ratio(medium_count, sentence_count),
        "long_sentence_ratio": _ratio(long_count, sentence_count),
        "dialogue_ratio": _ratio(dialogue_chars, sample_chars),
        "dialogue_sentence_ratio": _ratio(dialogue_sentence_count, sentence_count),
        "punctuation": punctuation[:8],
        "top_terms": top_terms,
        "overused_terms": overused_terms,
        "fatigue_terms": fatigue_terms,
    }
    stats["prompt"] = format_style_stats_prompt(stats)
    return stats


def format_style_stats_prompt(stats: dict | None) -> str:
    if not isinstance(stats, dict) or not stats.get("sample_chars"):
        return ""

    punctuation = "、".join(
        f"{item.get('mark')} {item.get('per_1000_chars')}/千字"
        for item in (stats.get("punctuation") or [])[:5]
    )
    top_terms = "、".join(
        f"{item.get('term')}×{item.get('count')}"
        for item in (stats.get("top_terms") or [])[:8]
    )
    overused = "、".join(
        f"{item.get('term')}×{item.get('count')}"
        for item in (stats.get("overused_terms") or [])[:6]
    )
    fatigue = "、".join(
        f"{item.get('term')}×{item.get('count')}"
        for item in (stats.get("fatigue_terms") or [])[:6]
    )

    lines = [
        "【本地文风统计约束】",
        f"- 样本规模：{stats.get('sample_chars', 0)} 字；{stats.get('paragraph_count', 0)} 段；{stats.get('sentence_count', 0)} 句。",
        (
            f"- 句长分布：平均 {stats.get('avg_sentence_chars', 0)} 字；"
            f"短句 {stats.get('short_sentence_ratio', 0)}%，中句 {stats.get('medium_sentence_ratio', 0)}%，长句 {stats.get('long_sentence_ratio', 0)}%。"
        ),
        f"- 段落长度：平均 {stats.get('avg_paragraph_chars', 0)} 字。",
        (
            f"- 对白比例：文本对白约 {stats.get('dialogue_ratio', 0)}%；"
            f"含对白句约 {stats.get('dialogue_sentence_ratio', 0)}%。"
        ),
    ]
    if punctuation:
        lines.append(f"- 标点节奏：{punctuation}。")
    if top_terms:
        lines.append(f"- 高频表达/意象：{top_terms}。")
    if overused or fatigue:
        risk = "；".join(part for part in [overused and f"高频词 {overused}", fatigue and f"疲劳词 {fatigue}"] if part)
        lines.append(f"- 重复风险：{risk}；生成时保留气质但避免机械复读。")
    lines.append("- 写作时让句长、对白密度、段落呼吸和标点节奏贴近样本，不要只模仿表面词汇。")
    return "\n".join(lines)


def format_style_samples_prompt(samples: list[dict] | None) -> str:
    usable = [item for item in (samples or []) if item.get("text")]
    if not usable:
        return ""
    lines = [
        "【文风样例片段】",
        "以下片段只用于学习句法、节奏、段落呼吸、对白密度和细节组织；不要复刻具体情节、专名或原句走向。",
    ]
    for index, item in enumerate(usable[:6], 1):
        label = item.get("label") or _SAMPLE_KIND_LABELS.get(item.get("kind", ""), "样例")
        lines.append(f"{index}. [{label}] {item.get('text')}")
    return "\n".join(lines)


def style_text_from_guide(style_guide: dict | None, fallback: str = "") -> str:
    guide = style_guide if isinstance(style_guide, dict) else {}
    style = guide.get("style", "") if isinstance(guide.get("style", ""), str) else ""
    stats_prompt = guide.get("style_stats_prompt", "") if isinstance(guide.get("style_stats_prompt", ""), str) else ""
    if not stats_prompt:
        stats_prompt = format_style_stats_prompt(guide.get("style_stats"))
    samples_prompt = guide.get("style_samples_prompt", "") if isinstance(guide.get("style_samples_prompt", ""), str) else ""
    if not samples_prompt:
        samples_prompt = format_style_samples_prompt(guide.get("style_samples"))
    parts = [part for part in [style.strip(), stats_prompt.strip(), samples_prompt.strip()] if part]
    return "\n\n".join(parts) or fallback