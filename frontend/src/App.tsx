import { useState } from "react";
import Projects from "./pages/Projects";
import Writer from "./pages/Writer";

type Tab = "projects" | "writer";

export default function App() {
  const [tab, setTab] = useState<Tab>("projects");

  return (
    <div className="app">
      <h1>AI Agent 小说写作系统 · 阶段 5</h1>
      <nav className="tabs">
        <button className={tab === "projects" ? "active" : ""} onClick={() => setTab("projects")}>
          项目管理
        </button>
        <button className={tab === "writer" ? "active" : ""} onClick={() => setTab("writer")}>
          章节写作
        </button>
      </nav>
      {tab === "projects" ? <Projects /> : <Writer />}
    </div>
  );
}
