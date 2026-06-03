import { useRef, useState } from "react";
import { streamSSE } from "../api/sse";

type Status = "idle" | "writing" | "done" | "error";

type WriterProps = {
  model?: string;
};

export default function Writer({ model }: WriterProps) {
  const [premise, setPremise] = useState(
    "一个生活在赛博朋克都市的年轻黑客，偶然发现了一段能改写记忆的代码。"
  );
  const [style, setStyle] = useState("冷峻、有画面感，带一点悬疑氛围。");
  const [outline, setOutline] = useState(
    "主角深夜潜入公司服务器，触发了那段代码，眼前的世界开始扭曲。"
  );
  const [wordCount, setWordCount] = useState(1500);

  const [status, setStatus] = useState<Status>("idle");
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const running = status === "writing";

  async function generate() {
    setContent("");
    setError("");
    setStatus("writing");

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamSSE(
        "/api/chapters/generate",
        {
          premise,
          style,
          chapter_outline: outline,
          word_count: wordCount,
          model: model || undefined,
        },
        {
          signal: controller.signal,
          onToken: (text) => setContent((prev) => prev + text),
          onDone: () => setStatus("done"),
          onError: (message) => {
            setError(message);
            setStatus("error");
          },
        }
      );
      setStatus((s) => (s === "error" ? s : "done"));
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setError((e as Error).message);
      setStatus("error");
    }
  }

  function stop() {
    abortRef.current?.abort();
    setStatus("idle");
  }

  return (
    <div className="layout">
      <div className="panel">
        <label>故事设定</label>
        <textarea rows={3} value={premise} onChange={(e) => setPremise(e.target.value)} />

        <label>文风要求</label>
        <textarea rows={2} value={style} onChange={(e) => setStyle(e.target.value)} />

        <label>本章大纲</label>
        <textarea rows={4} value={outline} onChange={(e) => setOutline(e.target.value)} />

        <label>目标字数</label>
        <input
          type="number"
          min={200}
          max={6000}
          step={100}
          value={wordCount}
          onChange={(e) => setWordCount(Number(e.target.value))}
        />

        {running ? (
          <button onClick={stop}>停止生成</button>
        ) : (
          <button onClick={generate} disabled={!outline.trim()}>
            生成本章
          </button>
        )}
      </div>

      <div className="panel">
        <div className="status">
          状态：
          {status === "idle" && "等待开始"}
          {status === "writing" && "写作中…"}
          {status === "done" && `完成（约 ${content.length} 字）`}
          {status === "error" && <span className="error">出错</span>}
        </div>
        {error && <div className="error">错误：{error}</div>}
        <div className="output">{content || "生成的小说正文将显示在这里。"}</div>
      </div>
    </div>
  );
}
