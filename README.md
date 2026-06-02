# AI Agent 小说写作系统

由多个 AI Agent 协作完成长篇小说创作的系统。后端 FastAPI + Anthropic Claude，前端 React。

> 架构设计见 [docs/architecture.md](docs/architecture.md)。已落地**阶段 1–5**：多 Agent 协作（大纲/角色/写作/审校/修订）、三层记忆（摘要/关键词 RAG/实体状态）、审改闭环与去 AI 味。

## 目录结构

```
backend/    FastAPI + Claude 流式生成 API
frontend/   Vite + React 流式写作界面
docs/       架构设计文档
```

## 快速开始

### 1. 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 配置 API Key
Copy-Item .env.example .env
# 编辑 .env：填入 ANTHROPIC_API_KEY；如需走本地/自定义代理，设置 ANTHROPIC_BASE_URL

uvicorn app.main:app --reload --port 8000
```

后端启动后：
- 健康检查：http://localhost:8000/health
- 接口文档：http://localhost:8000/docs

### 2. 前端

```powershell
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 ，填写设定与本章大纲，点击「生成本章」即可看到流式生成的小说正文。

> 前端通过 Vite 代理把 `/api` 请求转发到 `http://localhost:8000`，无需额外配置跨域。

## 已实现（阶段 1–5）

- ✅ FastAPI 服务 + CORS，Claude 流式生成封装（`anthropic` SDK）
- ✅ 多 Agent：大纲 / 角色 / 写作 / 审校 / 修订 Agent（tool-use 结构化输出）
- ✅ 数据库持久化项目 / 卷 / 章节 / 设定 / 审校报告
- ✅ 三层记忆：分层摘要、关键词 RAG、实体状态追踪
- ✅ 审校闭环：生成→审校→自动修订，一致性报告与去 AI 味 / AIGC 检测维度
- ✅ React 三栏式项目工作台 + 流式写作界面

## 下一步

详见架构文档第 9 节“分阶段实施路线”（阶段 6–7：全书批量生成、向量检索等）。
