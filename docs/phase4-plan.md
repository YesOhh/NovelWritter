# 阶段 4：审校 Agent + 一致性检测闭环

## Context

阶段 3 建立了三层记忆，写作时能注入设定/摘要/实体状态。但成稿**没有自动校验**——是否与设定矛盾、人设是否崩坏、伏笔是否遗漏，全靠人工。阶段 4（架构文档 §3 审校 Agent）补上"写作→审校"闭环：

- **审校 Agent**：拿成稿 + Context Pack（设定/角色/实体状态/前情摘要），用 tool use 产出**结构化一致性报告**（问题列表：类型/严重度/定位/建议）。
- **闭环**：章节生成 `done` 后自动触发审校（SSE `reviewing`→`reviewed`），报告落库；也支持对已成稿章节**单独重审**。
- **不引入 LangGraph**：现有代码是轻量 async 函数风格，闭环逻辑简单（写→审，无多轮自动重写），保持一致、避免过度工程。预留后续"按报告自动修订"的扩展点。

## 新增数据表（models）
- `ChapterReview(id, chapter_id, issues[json], summary, model, created_at)`
  - `issues`: `[{type, severity, location, description, suggestion}]`
  - `type`: contradiction（设定矛盾）/ character（人设崩坏）/ plot（情节漏洞）/ foreshadow（伏笔遗漏）/ style（文风偏移）/ other
  - `severity`: high / medium / low
> 加新表 → init_db 自动建（已清库重置，无需迁移）。

## 审校 Agent `backend/app/agents/reviewer_agent.py`
- `review_chapter(content, premise, style, characters, entity_states, recent_summaries, chapter_outline, model) -> dict`
- tool use 强制结构化：`{ "issues": [...], "summary": "总体评价" }`
- 无问题时返回空 issues + 正面 summary。

## 端点（generate.py）
- 写作链路：`done` 后新增 `reviewing` 阶段 → 调 `review_chapter` → 落 `ChapterReview` → SSE `reviewed`（带报告）。顺序：成稿 → 摘要/索引/实体（记忆）→ 审校。审校失败不影响正文（`review_error`）。
- 新增 `POST /api/chapters/{chapter_id}/review`：对已成稿章节单独重审，返回最新报告（非流式，JSON）。
- `GET` 项目详情已含章节；为暴露报告，`ChapterOut` 加 `review` 字段（最近一次）。

## Schema
- `ReviewIssue(type, severity, location, description, suggestion)`
- `ChapterReviewOut(issues, summary, created_at)`
- `ChapterOut.review: ChapterReviewOut | None`

## 前端（Projects.tsx）
- 章节卡：成稿后展示审校徽标（按最高严重度着色）+ 可展开的问题列表与总评。
- 「重新审校」按钮调用 review 端点。
- SSE 加 `reviewing`/`reviewed` 阶段文案。

## 验证（scripts/verify_phase4.py）
建项目→角色→大纲→生成第1章（含审校）→断言收到 `reviewed` 且报告结构正确→查 DB `chapter_reviews` 落库→单独调 review 端点重审→tsc 通过。全程走配置的 LLM 端点。
