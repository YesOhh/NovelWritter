import { useEffect, useState } from "react";
import { api } from "./api/client";
import Projects from "./pages/Projects";
import Writer from "./pages/Writer";

type Tab = "projects" | "writer";
const MODEL_STORAGE_KEY = "novel-writer.global-model";

export default function App() {
  const [tab, setTab] = useState<Tab>("projects");
  const [models, setModels] = useState<string[]>([]);
  const [globalModel, setGlobalModel] = useState("");
  const [defaultModel, setDefaultModel] = useState("");

  useEffect(() => {
    api.listModels()
      .then((result) => {
        const available = result.models ?? [];
        const stored = localStorage.getItem(MODEL_STORAGE_KEY) ?? "";
        const fallback = result.default || available[0] || "";
        setModels(available);
        setDefaultModel(fallback);
        setGlobalModel(stored);
      })
      .catch(() => {
        const stored = localStorage.getItem(MODEL_STORAGE_KEY) ?? "";
        setGlobalModel(stored);
      });
  }, []);

  function changeGlobalModel(model: string) {
    setGlobalModel(model);
    if (model) localStorage.setItem(MODEL_STORAGE_KEY, model);
    else localStorage.removeItem(MODEL_STORAGE_KEY);
  }

  const modelOptions = globalModel && !models.includes(globalModel)
    ? [globalModel, ...models]
    : models;

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title-block">
          <h1>AI Agent 小说写作系统</h1>
          <nav className="tabs">
            <button className={tab === "projects" ? "active" : ""} onClick={() => setTab("projects")}>
              项目管理
            </button>
            <button className={tab === "writer" ? "active" : ""} onClick={() => setTab("writer")}>
              章节写作
            </button>
          </nav>
        </div>
        <label className="global-model-control">
          <span>全局模型</span>
          <select value={globalModel} onChange={(e) => changeGlobalModel(e.target.value)}>
            <option value="">后端默认{defaultModel ? `：${defaultModel}` : ""}</option>
            {modelOptions.map((modelName) => (
              <option key={modelName} value={modelName}>
                {modelName}
              </option>
            ))}
          </select>
        </label>
      </header>
      {tab === "projects" ? <Projects model={globalModel} /> : <Writer model={globalModel} />}
    </div>
  );
}
