# 阶段 3：记忆系统（分层摘要 + 轻量 RAG + 实体状态追踪）

## Context

阶段 2.5 让写作接入项目，但"前情"只是机械拼接上一章结尾 600 字——跨多卷会丢伏笔/配角/历史。阶段 3（架构文档 §4 核心）建立三层记忆：
- **L2 分层摘要**：每章成稿生成摘要，卷级聚合；写作时注入卷摘要+最近几章摘要。
- **L3 轻量 RAG**：设定/角色/章节摘要做成片段，按本章大纲关键词召回 top-k。
- **L4 实体状态**：每章后用 Claude 抽取角色状态变更，写作时注入当前状态，避免"已死复活"。

**选型**：当前 LLM 端点不提供 embedding（已探测 404）→ 用关键词检索（Claude 抽关键词，按重叠打分），预留 Retriever 接口可换向量。实体状态追踪本阶段做。

## 新增数据表（models）
- `ChapterSummary(id, chapter_id, summary, keywords)`
- `EntityState(id, character_id, chapter_id, state)`
- `MemoryChunk(id, project_id, source_type, source_id, text, keywords)`
- `Volume` 加 `summary`
> 加了新列 → 删 `backend/novel.db` 重建（测试数据）。

## 记忆服务 `backend/app/memory/`
- `summarizer.py`：`summarize_chapter`（tool use，摘要+关键词）、`summarize_volume`
- `retriever.py`：`Retriever` 类，`index_chunk` / `retrieve`（关键词重叠打分 top-k）
- `entity_tracker.py`：`extract_entity_states`（tool use）、`current_states`

## 写作链路升级（generate.py）
Context Pack 升级：设定 + 本章大纲 + 卷摘要 + 最近章摘要 + RAG 召回 + 角色当前状态 + 上一章结尾。
成稿 `done` 后追加记忆流水（SSE `indexing`→`indexed`）：summarize → index → extract_entity_states。

## 生成后初始化索引（projects.py）
角色/大纲生成端点末尾把内容 index_chunk 进 MemoryChunk。

## 前端
章节卡展示摘要；SSE 加 indexing/indexed 状态文案。

## 验证
建项目→角色+大纲→看 MemoryChunk→生成第1章→确认摘要/状态/片段落库→生成第2章看是否注入前情→连续几章看连贯性。全程走配置的 LLM 端点，tsc 通过。
