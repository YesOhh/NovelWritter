# 阶段 5：审改自动闭环 + 去 AI 味

## Context

阶段 4 的审校 Agent 只**产报告不改稿**——发现问题后仍要人工修。对标 InkOS 的 Reviser，本阶段补上"审→改→再审"闭环；同时针对 LLM 生成的"AI 味"（高频词、句式单调、过度总结收尾、解释性旁白）做源头抑制 + 事后检测/改写。这是把现有审校系统价值翻倍的一步。

两件事天然耦合：**去 AI 味本质就是一种定向修订**，故合并为一个阶段。

## 1. 修订 Agent `backend/app/agents/reviser_agent.py`
- `revise_chapter(content, issues, premise, style, characters, entity_states, chapter_outline, mode, model) -> str`（流式或整段返回修订后正文）。
- 输入原文 + 审校 issues（按 severity 排序），定向修复矛盾/人设/情节/伏笔问题，**保持未涉及部分尽量不动**、保持字数与文风。
- `mode`：
  - `fix`（默认）：按 issues 修复一致性问题。
  - `anti-detect`：专做去 AI 味改写（打散句式、替换疲劳词、删除解释性总结），不改情节。
- 返回纯正文（不带解释）。

## 2. 去 AI 味规则集 `backend/app/agents/style_rules.py`
集中维护，供写手与修订共享：
- **疲劳词表**：过度使用的词（"仿佛/彷佛、似乎、一丝、不禁、嘴角、眼神、空气仿佛凝固、心中一紧"等）。
- **禁用句式**：万能排比"不是…而是…"、解释性收尾"这一刻他明白了…"、过度总结段。
- **正向指引**：多用具体动作/细节代替情绪标签、对话推进、留白。
- 导出 `ANTI_AI_GUIDELINES`（注入写手/修订 system prompt）与 `FATIGUE_WORDS`（供检测打分）。

## 3. 写手 prompt 注入去 AI 味
`writer_agent.py` 的 `WRITER_SYSTEM_PROMPT` 追加 `ANTI_AI_GUIDELINES`，从源头减少 AI 痕迹。

## 4. 审校加 ai_flavor 维度
`reviewer_agent.py`：
- tool schema 的 `type` enum 增加 `ai_flavor`。
- system prompt 增加"AI 味检测"说明（高频词、句式单调、过度总结、解释性旁白）。
- 新增轻量本地打分 `ai_flavor_score(text) -> {score, hits}`：基于 `FATIGUE_WORDS` 词频 + 重复句式统计，0–100，随报告返回（不额外调 LLM）。

## 5. 自动修订闭环（generate.py）
写作链路在 `reviewed` 之后：
- 若报告含 high/medium issues 且 `review_retries > 0`：调 `revise_chapter(mode=fix)` → 回写正文 → 重新摘要/实体（记忆刷新）→ 再审一轮 → 发 SSE `revised`（带轮次、改前后 issue 数）。
- 最多 `review_retries` 轮（默认 1）。仍存问题则保留，标记人工。
- 配置：`config.py` 加 `review_retries: int = 1`（env `REVIEW_RETRIES`）。

## 6. 端点
- `POST /api/chapters/{id}/revise`：对已成稿章节手动修订。body `{ mode: "fix"|"anti-detect", model? }`。返回新正文 + 新审校报告。落库（更新 chapter.content + 新 ChapterReview）。

## 7. Schema
- `ChapterReviewOut` 加 `ai_flavor_score: int`、`ai_flavor_hits: list[str]`。
- `ReviseRequest(mode: str = "fix", model: str | None)`。
- `ReviseResult(content, review)`。

## 8. 前端（Projects.tsx）
- 审校徽标旁显示 AI 味分数（颜色分级）。
- 「自动修订」「去 AI 味」两个按钮（调 revise 端点 fix / anti-detect）。
- 生成链路 SSE 新增 `revising`/`revised` 阶段文案。

## 9. 验证（scripts/verify_phase5.py）
建项目→角色→大纲→生成第1章（含可能的自动修订）→断言收到 `reviewed`，若有 high/medium 则收到 `revised`→手动调 revise(fix) 与 revise(anti-detect) 端点→断言返回新正文与 ai_flavor_score→DB 落库核对。全程走配置的 LLM 端点。tsc 通过。
