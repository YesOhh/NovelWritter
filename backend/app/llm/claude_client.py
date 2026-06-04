"""Anthropic Claude 客户端封装：提供流式生成。"""
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.config import settings

# 构建客户端：若配置了 anthropic_base_url（如本地 Anthropic 兼容代理），则指向该端点。
_client_kwargs: dict = {}
if settings.anthropic_api_key:
    _client_kwargs["api_key"] = settings.anthropic_api_key
elif settings.anthropic_auth_token:
    _client_kwargs["auth_token"] = settings.anthropic_auth_token
else:
    _client_kwargs["api_key"] = "local-proxy"
if settings.anthropic_base_url:
    _client_kwargs["base_url"] = settings.anthropic_base_url

_client = AsyncAnthropic(**_client_kwargs)


async def stream_completion(
    system: str,
    prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.8,
    model: str | None = None,
) -> AsyncIterator[str]:
    """以流式方式调用 Claude，逐段产出文本增量。"""
    async with _client.messages.stream(
        model=model or settings.claude_model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def ocr_images(
    images: list[dict],
    instruction: str = "",
    max_tokens: int = 8192,
    model: str | None = None,
) -> str:
    """调用 Claude 视觉能力，将一张或多张图片识别为文本并按顺序拼接。

    images: [{"media_type": "image/png", "data": "<base64>"}...]
    """
    system = (
        "你是高精度 OCR 助手。请逐字转写图片中的所有可见文字，保持原有段落与换行，"
        "不要翻译、不要润色、不要补充解释或评论。只输出识别到的正文文本。"
        "若图片中没有文字，输出空字符串。"
    )
    user_text = instruction.strip() or "请把下面图片中的文字按阅读顺序完整转写出来。"
    content: list[dict] = [{"type": "text", "text": user_text}]
    for img in images:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img["media_type"],
                    "data": img["data"],
                },
            }
        )
    resp = await _client.messages.create(
        model=model or settings.claude_model,
        max_tokens=max_tokens,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    parts = [block.text for block in resp.content if getattr(block, "type", "") == "text"]
    return "".join(parts).strip()


async def complete_json(
    system: str,
    prompt: str,
    tool_name: str,
    tool_schema: dict,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    model: str | None = None,
) -> dict:
    """通过 tool use 强制 Claude 返回结构化数据，返回该工具调用的入参 dict。"""
    tool = {
        "name": tool_name,
        "description": f"保存生成结果。必须调用此工具以返回结构化数据。",
        "input_schema": tool_schema,
    }
    resp = await _client.messages.create(
        model=model or settings.claude_model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    raise ValueError("模型未按预期调用结构化输出工具")
