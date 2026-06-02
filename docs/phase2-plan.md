# 阶段 2：持久化 + 大纲/角色 Agent

## Context

当前项目处于阶段 1 (MVP)：已打通 `React 表单 → FastAPI SSE → writer_agent → Claude` 的单章流式写作链路，但**生成完即丢，无任何持久化**，也没有结构化的项目/设定/大纲概念。

阶段 2 的目标（对照 [architecture.md](architecture.md) §9）：引入数据库，让作品能**存下来、成体系**，并新增**大纲 Agent**和**角色 Agent**，使系统从"单次生成器"变成"可管理的小说项目"。

技术选型（已与用户确认）：
- **SQLite 起步**（零依赖，文件落地 `backend/novel.db`；阶段 3 上 RAG 时再迁 PostgreSQL）
- **只建阶段 2 核心 5 张表**：PROJECT / VOLUME / CHAPTER / CHARACTER / WORLD_SETTING
- **大纲/角色 Agent 返回结构化 JSON**（非流式），一次返回后落库

## 实现方案

### 1. 依赖 (`backend/requirements.txt`)
新增：
- `sqlalchemy==2.0.35`
- `aiosqlite==0.20.0`（async SQLite 驱动）

> 暂不引入 Alembic：阶段 2 用 `create_all` 自动建表足够；阶段 3 schema 稳定后再上迁移。

### 2. 数据库基础设施（新增 `backend/app/db.py`）
- async engine：`sqlalchemy.ext.asyncio.create_async_engine("sqlite+aiosqlite:///<backend>/novel.db")`
- `async_sessionmaker` → `get_session()` 依赖（FastAPI `Depends`）
- `Base = DeclarativeBase`
- `init_db()`：启动时 `Base.metadata.create_all`，在 `main.py` 的 lifespan/startup 调用
- DB 文件路径用 `Path(__file__).resolve().parent.parent / "novel.db"`，与 `config.py` 定位 `.env` 同款绝对路径写法

### 3. SQLAlchemy 模型（新增 `backend/app/models/__init__.py`）
按 architecture.md §5 的 5 张表，主键用 `str` UUID（`default=lambda: str(uuid4())`，SQLite 无原生 UUID）：
- `Project(id, title, genre, premise, style_guide(JSON), created_at)`
- `Volume(id, project_id FK, order_index, title, outline)`
- `Chapter(id, volume_id FK, order_index, title, outline, content, status, word_count)`
- `Character(id, project_id FK, name, profile(JSON), arc)`
- `WorldSetting(id, project_id FK, category, key, value)`
- 关系用 `relationship` + `cascade="all, delete-orphan"`；JSON 字段用 `sqlalchemy.JSON`

### 4. Pydantic Schemas（新增 `backend/app/schemas/__init__.py`）
每个实体一组 `XxxCreate` / `XxxOut`（`model_config = ConfigDict(from_attributes=True)`）。
新增 Agent 输出 schema：
- `OutlineResult { volumes: [{ title, outline, chapters: [{ title, outline }] }] }`
- `CharacterResult { characters: [{ name, profile: {personality, motivation, relationships, appearance}, arc }] }`

### 5. 新 Agent（结构化 JSON 输出）
复用现有 `claude_client.py` 模式，但新增一个**非流式** `complete_json()`：用 `_client.messages.create(...)` + tool use（强制结构化输出）解析为 dict。

- 新增 `backend/app/agents/outline_agent.py` → `generate_outline(premise, genre, style, volume_count, chapters_per_volume) -> OutlineResult`
- 新增 `backend/app/agents/character_agent.py` → `generate_characters(premise, genre, count) -> CharacterResult`
- 两者各有专属 system prompt（参考 architecture.md §3 的职责表：大纲师重三幕结构/伏笔，角色师重立体化/动机/关系网）

> 结构化输出实现：用 Anthropic **tool use**（定义一个 `save_outline`/`save_characters` 工具，`tool_choice` 强制调用），比"请返回 JSON"更稳。`anthropic==0.69.0` 已支持。

### 6. API 路由
- 新增 `backend/app/api/projects.py`：
  - `POST /api/projects`（创建项目）
  - `GET /api/projects`（列表）
  - `GET /api/projects/{id}`（详情，含 volumes/characters/settings）
  - `POST /api/projects/{id}/characters/generate`（角色 Agent → 落库 → 返回）
  - `POST /api/projects/{id}/outline/generate`（大纲 Agent → 落库 volumes+chapters → 返回）
- 新增 `backend/app/api/settings.py`：WorldSetting 的 CRUD（`GET/POST /api/projects/{id}/settings`、`PUT/DELETE /api/settings/{sid}`）
- `main.py` 注册新 router + startup 调 `init_db()`

> 现有 `/api/chapters/generate` 保持不变（阶段 3 再接入项目上下文），阶段 2 不动写作链路。

### 7. 前端（最小联动，`frontend/src/`）
范围控制在"能验证后端"：
- 新增项目列表/创建（`App.tsx` 加 tab，或拆 `pages/Projects.tsx`）
- 项目详情页：按钮触发"生成角色""生成大纲"，展示返回的结构化结果
- 新增 `src/api/client.ts` 封装 fetch
- Vite 代理已覆盖 `/api`，无需改 `vite.config.ts`

> 前端做到"可点、可看到落库结果"即可，富文本编辑器等留到阶段 5。

## 关键文件清单
- 新增：`backend/app/db.py`、`backend/app/models/__init__.py`、`backend/app/schemas/__init__.py`、`backend/app/agents/outline_agent.py`、`backend/app/agents/character_agent.py`、`backend/app/api/projects.py`、`backend/app/api/settings.py`、`frontend/src/api/client.ts`
- 修改：`backend/requirements.txt`、`backend/app/main.py`、`backend/app/llm/claude_client.py`（加 `complete_json`）、`frontend/src/App.tsx`
- `.gitignore` 加 `backend/novel.db`

## 验证
1. `pip install -r requirements.txt` 装新依赖
2. 重启后端（先停旧实例避免端口占用），确认 `novel.db` 自动生成、`/health` OK
3. `POST /api/projects` 建项目 → `GET /api/projects` 能查到
4. `POST /api/projects/{id}/characters/generate` → 返回结构化角色卡且落库
5. `POST /api/projects/{id}/outline/generate` → 返回分卷分章大纲且落库
6. 前端 `npm run dev`，建项目 → 点生成角色/大纲 → 看到结果
7. 确认生成链路走配置的 LLM 端点，未硬编码个人 key
