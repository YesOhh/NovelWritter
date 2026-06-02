# 阶段 2.5：写作链路接入项目（轻量关联）

## Context

当前「项目管理」与「章节写作」两个 tab 是割裂的：
- 项目管理：项目/角色/大纲落库（`frontend/src/pages/Projects.tsx`）
- 章节写作：手填设定+大纲 → 流式生成 → **结果只显示在屏幕、不落库**，且**不读取项目里已生成的角色/大纲**（`frontend/src/pages/Writer.tsx` + `backend/app/api/generate.py`）

本阶段（方案 A，阶段 3 RAG 之前的过渡）目标：让写作真正接入项目——**从大纲章节点生成 → 后端按 chapter_id 自动拼装项目上下文 → 流式生成 → 成稿回写到该章节**。"前情"先用简单方式（上一章正文/摘要直接拼），精准 RAG 召回留到阶段 3。

选择：
- **入口**：在项目详情大纲的每个章节旁加「生成/重写」按钮
- **章节状态**：生成成稿后 `outlined → drafted`

## 实现方案

### 1. 项目感知写作端点（后端 `generate.py`）
现有 `/api/chapters/generate`（无状态，入参直接是文本）保留不动。
新增 `POST /api/chapters/{chapter_id}/generate`（SSE）：
- 按 chapter_id 反查 Chapter → Volume → Project
- 查同项目 Character 列表拼角色卡、本章+卷 outline、上一章结尾片段
- 组装 Context Pack 喂写作 Agent，流式产出
- 流结束后把全文写回 `chapter.content` / `word_count` / `status="drafted"`

### 2. 写作 Agent 增强（`writer_agent.py`）
新增 `build_context_pack_prompt(...)`，接收设定/文风/角色卡/卷大纲/本章大纲/上一章结尾/字数，拼结构化 prompt；复用 `WRITER_SYSTEM_PROMPT`。

### 3. 新增 schema：`ChapterGenerateRequest { word_count, model }`

### 4. 前端
- `Projects.tsx`：大纲每章加「生成/重写」按钮，章节卡显示 status 徽标+字数+正文
- 抽取 SSE 读取逻辑为 `frontend/src/api/sse.ts`，Writer 与 Projects 共用
- `client.ts` 提供端点 URL

## 验证
1. 建项目 → 生成大纲（outlined 章节）
2. 某章点生成 → 流式正文 → 完成后 drafted
3. `GET /api/projects/{id}` 确认该章 content 非空、status=drafted、word_count>0
4. 确认设定/角色来自库（非前端手填）
5. 全程走配置的 LLM 端点；前端 tsc 通过
