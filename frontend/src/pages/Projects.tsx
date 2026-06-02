import { useEffect, useState } from "react";
import {
  api,
  type Project,
  type ProjectDetail,
  type CharacterOut,
  type VolumeOut,
  type ReviewIssue,
} from "../api/client";
import { streamSSE } from "../api/sse";

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<ProjectDetail | null>(null);
  const [title, setTitle] = useState("");
  const [genre, setGenre] = useState("赛博朋克");
  const [premise, setPremise] = useState(
    "一个生活在赛博朋克都市的年轻黑客，偶然发现了一段能改写记忆的代码。"
  );
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState("");

  // 章节写作流式状态：当前正在生成的章节 id 与其实时正文。
  const [writingChapter, setWritingChapter] = useState<string>("");
  const [chapterText, setChapterText] = useState("");
  const [phase, setPhase] = useState<string>("");
  // 单独重审中的章节 id。
  const [reviewingChapter, setReviewingChapter] = useState<string>("");
  // 修订中的章节 id（fix / anti-detect）。
  const [revisingChapter, setRevisingChapter] = useState<string>("");
  // 主区当前查看/写作的章节 id。
  const [activeChapter, setActiveChapter] = useState<string>("");
  // 新建项目表单是否展开。
  const [showCreate, setShowCreate] = useState(false);

  async function refresh() {
    try {
      setProjects(await api.listProjects());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function open(id: string) {
    setError("");
    try {
      const detail = await api.getProject(id);
      setSelected(detail);
      // 默认选中第一章，避免主区空白。
      const first = detail.volumes[0]?.chapters[0]?.id ?? "";
      setActiveChapter((prev) => {
        const stillExists = detail.volumes.some((v) =>
          v.chapters.some((c) => c.id === prev)
        );
        return stillExists ? prev : first;
      });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(id: string) {
    if (!confirm("确定删除该项目？其角色、大纲、设定将一并删除。")) return;
    setError("");
    try {
      await api.deleteProject(id);
      if (selected?.id === id) setSelected(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function create() {
    if (!title.trim()) return;
    setError("");
    try {
      const p = await api.createProject({ title, genre, premise });
      setTitle("");
      setShowCreate(false);
      await refresh();
      await open(p.id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function genCharacters() {
    if (!selected) return;
    setBusy("characters");
    setError("");
    try {
      await api.generateCharacters(selected.id, 4);
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function genOutline() {
    if (!selected) return;
    setBusy("outline");
    setError("");
    try {
      await api.generateOutline(selected.id, 3, 5);
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function genChapter(chapterId: string) {
    if (!selected) return;
    setActiveChapter(chapterId);
    setWritingChapter(chapterId);
    setChapterText("");
    setPhase("writing");
    setError("");
    try {
      await streamSSE(
        `/api/chapters/${chapterId}/generate`,
        { word_count: 1500 },
        {
          onToken: (text) => setChapterText((prev) => prev + text),
          onError: (message) => setError(message),
          onEvent: (event, data) => {
            if (event === "status" && data.stage === "indexing") setPhase("indexing");
            else if (event === "indexed") setPhase("indexed");
            else if (event === "status" && data.stage === "reviewing") setPhase("reviewing");
            else if (event === "reviewed") setPhase("reviewed");
            else if (event === "status" && data.stage === "revising") setPhase("revising");
            else if (event === "revised") {
              setPhase("revised");
              if (typeof data.content === "string") setChapterText(data.content);
            }
          },
        }
      );
      await open(selected.id); // 刷新，章节状态变 drafted、带回正文与摘要
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setWritingChapter("");
      setPhase("");
    }
  }

  async function reviewChapter(chapterId: string) {
    if (!selected) return;
    setReviewingChapter(chapterId);
    setError("");
    try {
      await api.reviewChapter(chapterId);
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setReviewingChapter("");
    }
  }

  async function reviseChapter(chapterId: string, mode: "fix" | "anti-detect") {
    if (!selected) return;
    setRevisingChapter(chapterId);
    setError("");
    try {
      await api.reviseChapter(chapterId, mode);
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRevisingChapter("");
    }
  }

  // 当前主区查看的章节及其所属卷。
  const flatChapters =
    selected?.volumes.flatMap((v) =>
      v.chapters.map((ch) => ({ ch, vol: v }))
    ) ?? [];
  const activeEntry =
    flatChapters.find((e) => e.ch.id === activeChapter) ?? null;

  function severityOf(review: ReviewIssue[] | undefined): string {
    if (!review || review.length === 0) return "none";
    if (review.some((i) => i.severity === "high")) return "high";
    if (review.some((i) => i.severity === "medium")) return "medium";
    return "low";
  }

  function aiSevOf(score: number | null): string {
    if (score === null) return "none";
    if (score >= 50) return "high";
    if (score >= 25) return "medium";
    return "low";
  }

  return (
    <div className="workspace">
      {/* 左栏：项目列表 */}
      <aside className="rail">
        <div className="rail-head">
          <span>项目</span>
          <button
            className="mini"
            onClick={() => setShowCreate((s) => !s)}
            title="新建项目"
          >
            {showCreate ? "取消" : "+ 新建"}
          </button>
        </div>

        {showCreate && (
          <div className="create-form">
            <label>标题</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="作品名"
            />
            <label>题材</label>
            <input value={genre} onChange={(e) => setGenre(e.target.value)} />
            <label>一句话设定</label>
            <textarea
              rows={3}
              value={premise}
              onChange={(e) => setPremise(e.target.value)}
            />
            <button onClick={create} disabled={!title.trim()}>
              创建项目
            </button>
          </div>
        )}

        {projects.length === 0 && <div className="hint">暂无项目</div>}
        <ul className="project-list">
          {projects.map((p) => (
            <li key={p.id}>
              <button
                className={selected?.id === p.id ? "active" : ""}
                onClick={() => open(p.id)}
              >
                {p.title} <span className="genre">{p.genre}</span>
              </button>
              <button className="del" title="删除项目" onClick={() => remove(p.id)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* 中栏：章节导航 */}
      <nav className="chapter-nav">
        {!selected ? (
          <div className="hint">选择或新建一个项目。</div>
        ) : (
          <>
            <div className="nav-head">
              <h2 title={selected.premise}>{selected.title}</h2>
              <div className="actions">
                <button onClick={genCharacters} disabled={busy !== ""}>
                  {busy === "characters" ? "生成角色中…" : "生成角色"}
                </button>
                <button onClick={genOutline} disabled={busy !== ""}>
                  {busy === "outline" ? "生成大纲中…" : "生成大纲"}
                </button>
              </div>
            </div>

            {selected.characters.length > 0 && (
              <details className="nav-chars">
                <summary>角色（{selected.characters.length}）</summary>
                {selected.characters.map((c: CharacterOut) => (
                  <div key={c.id} className="card">
                    <strong>{c.name}</strong>
                    <div className="meta">动机：{c.profile.motivation}</div>
                    <div className="meta">性格：{c.profile.personality}</div>
                    <div className="meta">关系：{c.profile.relationships}</div>
                    <div className="meta">弧光：{c.arc}</div>
                  </div>
                ))}
              </details>
            )}

            {selected.volumes.length === 0 && (
              <div className="hint">还没有大纲，点上方「生成大纲」。</div>
            )}
            {selected.volumes.map((v: VolumeOut) => (
              <div key={v.id} className="nav-vol">
                <div className="nav-vol-title" title={v.outline}>
                  第 {v.order_index + 1} 卷 · {v.title}
                </div>
                <ul className="nav-chapters">
                  {v.chapters.map((ch) => {
                    const drafted = ch.status === "drafted";
                    const sev = severityOf(ch.review?.issues);
                    const isActive = ch.id === activeChapter;
                    const isWriting = writingChapter === ch.id;
                    return (
                      <li key={ch.id}>
                        <button
                          className={`nav-chapter ${isActive ? "active" : ""}`}
                          onClick={() => setActiveChapter(ch.id)}
                        >
                          <span className="nav-ch-title">{ch.title}</span>
                          <span className="nav-ch-badges">
                            {isWriting ? (
                              <span className="dot writing" />
                            ) : drafted ? (
                              <span className={`dot done sev-${sev}`} />
                            ) : (
                              <span className="dot todo" />
                            )}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </>
        )}
      </nav>

      {/* 右栏：正文主区 */}
      <main className="main-pane">
        {error && <div className="error">错误：{error}</div>}
        {!selected ? (
          <div className="hint center">从左侧选择项目开始创作。</div>
        ) : !activeEntry ? (
          <div className="hint center">生成大纲后，从中间选择章节。</div>
        ) : (
          (() => {
            const { ch, vol } = activeEntry;
            const drafted = ch.status === "drafted";
            const isWriting = writingChapter === ch.id;
            const isReviewing = reviewingChapter === ch.id;
            const isRevising = revisingChapter === ch.id;
            const review = ch.review;
            const aiScore = review?.ai_flavor_score ?? null;
            const aiSev = aiSevOf(aiScore);
            const maxSeverity = severityOf(review?.issues);
            return (
              <article className="chapter-detail">
                <header className="chapter-head">
                  <div className="crumbs">
                    第 {vol.order_index + 1} 卷 · {vol.title}
                  </div>
                  <h2>{ch.title}</h2>
                  <div className="badges">
                    <span className={`badge ${drafted ? "drafted" : ""}`}>
                      {drafted ? `已成稿 ${ch.word_count}字` : "待写"}
                    </span>
                    {drafted && review && (
                      <span className={`badge review sev-${maxSeverity}`}>
                        {review.issues.length === 0
                          ? "审校通过"
                          : `${review.issues.length} 处问题`}
                      </span>
                    )}
                    {drafted && review && aiScore !== null && (
                      <span className={`badge review sev-${aiSev}`}>
                        AI味 {aiScore}
                      </span>
                    )}
                  </div>
                  <div className="chapter-outline">大纲：{ch.outline}</div>
                  <div className="chapter-actions">
                    <button
                      className="gen"
                      disabled={isWriting || writingChapter !== ""}
                      onClick={() => genChapter(ch.id)}
                    >
                      {isWriting
                        ? phase === "indexing"
                          ? "建立记忆中…"
                          : phase === "reviewing"
                          ? "审校中…"
                          : phase === "revising"
                          ? "修订中…"
                          : "生成中…"
                        : drafted
                        ? "重写"
                        : "生成本章"}
                    </button>
                    {drafted && (
                      <>
                        <button
                          className="gen"
                          disabled={isReviewing || isRevising || writingChapter !== ""}
                          onClick={() => reviewChapter(ch.id)}
                        >
                          {isReviewing ? "审校中…" : "重新审校"}
                        </button>
                        <button
                          className="gen"
                          disabled={isRevising || isReviewing || writingChapter !== ""}
                          onClick={() => reviseChapter(ch.id, "fix")}
                        >
                          {isRevising ? "修订中…" : "自动修订"}
                        </button>
                        <button
                          className="gen"
                          disabled={isRevising || isReviewing || writingChapter !== ""}
                          onClick={() => reviseChapter(ch.id, "anti-detect")}
                        >
                          {isRevising ? "修订中…" : "去AI味"}
                        </button>
                      </>
                    )}
                  </div>
                </header>

                {isWriting && chapterText && (
                  <div className="output stream">{chapterText}</div>
                )}

                {!isWriting && drafted && (
                  <>
                    {ch.summary && (
                      <div className="meta summary">摘要：{ch.summary}</div>
                    )}
                    {review && (
                      <div className="review-report">
                        <div className="meta">审校总评：{review.summary}</div>
                        {review.issues.length > 0 && (
                          <ul className="issue-list">
                            {review.issues.map((issue: ReviewIssue, idx: number) => (
                              <li key={idx} className={`issue sev-${issue.severity}`}>
                                <span className="issue-tag">
                                  [{issue.type}/{issue.severity}]
                                </span>{" "}
                                {issue.description}
                                {issue.suggestion && (
                                  <div className="issue-fix">建议：{issue.suggestion}</div>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                    {ch.content && <div className="output">{ch.content}</div>}
                  </>
                )}

                {!isWriting && !drafted && (
                  <div className="hint center">本章尚未生成，点上方「生成本章」。</div>
                )}
              </article>
            );
          })()
        )}
      </main>
    </div>
  );
}
