"""Anthropic Claude 客户端封装：提供流式生成。"""
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.config import settings

# 构建客户端：若配置了 anthropic_base_url（如本地 Anthropic 兼容代理），则指向该端点。
_client_kwargs: dict = {"api_key": settings.anthropic_api_key or "local-proxy"}
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
