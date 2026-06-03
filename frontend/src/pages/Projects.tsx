import { useEffect, useState } from "react";
import {
  api,
  type Project,
  type ProjectDetail,
  type CharacterOut,
  type VolumeOut,
  type ReviewIssue,
  type WorldSettingOut,
  type ForeshadowOut,
  type TruthFileOut,
  type TruthFileCheckResult,
  type TruthMaintenanceAction,
  type TruthMaintenanceLogEntry,
  type TrackingSuggestion,
  type ReferenceAnalyzeResult,
  type ReferenceChapterImportResult,
  type ReferenceConflictItem,
  type ChapterContextPreview,
  type ContextPreviewMemoryChunk,
  type StyleSample,
  type StyleStats,
  type ExportFormat,
  type ExportOptions,
} from "../api/client";
import { streamSSE } from "../api/sse";

const OVERVIEW_ID = "__overview";

type ProjectsProps = {
  model?: string;
};

type ContinuationAnchor = {
  chapter_id?: string;
  chapter_title?: string;
  volume_id?: string;
  volume_title?: string;
};

function isStyleStats(value: unknown): value is StyleStats {
  return !!value && typeof value === "object" && !Array.isArray(value) &&
    typeof (value as StyleStats).sample_chars === "number";
}

function isStyleSampleArray(value: unknown): value is StyleSample[] {
  return Array.isArray(value) && value.every((item) =>
    item && typeof item === "object" && typeof (item as StyleSample).text === "string"
  );
}

function styleStatsOf(project: ProjectDetail | null): StyleStats | null {
  const value = project?.style_guide?.style_stats;
  return isStyleStats(value) && value.sample_chars > 0 ? value : null;
}

function styleSamplesOf(project: ProjectDetail | null): StyleSample[] {
  const value = project?.style_guide?.style_samples;
  return isStyleSampleArray(value) ? value.filter((item) => item.text.trim()) : [];
}

function styleTextOf(project: ProjectDetail | null): string {
  const value = project?.style_guide?.style;
  return typeof value === "string" ? value.trim() : "";
}

function isTruthMaintenanceLogArray(value: unknown): value is TruthMaintenanceLogEntry[] {
  return Array.isArray(value) && value.every((item) =>
    item && typeof item === "object" && typeof (item as TruthMaintenanceLogEntry).title === "string"
  );
}

function truthMaintenanceLogOf(project: ProjectDetail | null): TruthMaintenanceLogEntry[] {
  const value = project?.style_guide?.truth_maintenance_log;
  return isTruthMaintenanceLogArray(value) ? value : [];
}

function truthActionKey(action: TruthMaintenanceAction, index: number): string {
  return [action.action_type, action.target_type, action.target_id, action.suggested_status, index].join(":");
}

function canApplyTruthAction(action: TruthMaintenanceAction): boolean {
  return action.action_type === "update_truth_status" &&
    action.target_type === "truth_file" &&
    Boolean(action.target_id && action.suggested_status);
}

function formatPercent(value: number | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "0%";
  return `${n.toFixed(n % 1 === 0 ? 0 : 1)}%`;
}

function termsText(items: Array<{ term: string; count: number }> | undefined, limit = 6): string {
  return (items ?? []).slice(0, limit).map((item) => `${item.term}×${item.count}`).join("、") || "-";
}

function StyleStatsPanel({ stats, compact = false }: { stats: StyleStats; compact?: boolean }) {
  return (
    <div className={compact ? "style-stats compact" : "style-stats"}>
      <div className="style-stat-grid">
        <div><span>样本</span><strong>{stats.sample_chars}</strong><small>{stats.paragraph_count} 段 · {stats.sentence_count} 句</small></div>
        <div><span>平均句长</span><strong>{stats.avg_sentence_chars}</strong><small>短 {formatPercent(stats.short_sentence_ratio)} · 长 {formatPercent(stats.long_sentence_ratio)}</small></div>
        <div><span>平均段落</span><strong>{stats.avg_paragraph_chars}</strong><small>字/段</small></div>
        <div><span>对白</span><strong>{formatPercent(stats.dialogue_ratio)}</strong><small>对白句 {formatPercent(stats.dialogue_sentence_ratio)}</small></div>
      </div>
      <div className="style-chip-row">
        <span>高频：{termsText(stats.top_terms)}</span>
        {(stats.overused_terms ?? []).length > 0 && <span>重复风险：{termsText(stats.overused_terms, 4)}</span>}
        {(stats.punctuation ?? []).length > 0 && (
          <span>标点：{(stats.punctuation ?? []).slice(0, 4).map((item) => `${item.mark} ${item.per_1000_chars}/千字`).join("、")}</span>
        )}
      </div>
      {!compact && stats.prompt && (
        <details className="style-prompt-details">
          <summary>写作约束</summary>
          <div className="style-prompt-snippet">{stats.prompt}</div>
        </details>
      )}
    </div>
  );
}

function StyleSamplesPanel({ samples, compact = false }: { samples: StyleSample[]; compact?: boolean }) {
  const usable = (samples ?? []).filter((item) => item.text.trim()).slice(0, compact ? 3 : 6);
  if (usable.length === 0) return null;
  return (
    <div className={compact ? "style-samples compact" : "style-samples"}>
      <div className="style-samples-head">
        <strong>样例片段库</strong>
        <span>{usable.length} 段</span>
      </div>
      <div className="style-sample-list">
        {usable.map((sample, idx) => (
          <div key={`${sample.kind}-${idx}`} className="style-sample-item">
            <div>
              <b>{sample.label || sample.kind || "样例"}</b>
              <small>{sample.char_count || sample.text.length} 字</small>
            </div>
            <p>{sample.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Projects({ model }: ProjectsProps) {
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
  const [suggestingChapter, setSuggestingChapter] = useState<string>("");
  const [suggestionsChapter, setSuggestionsChapter] = useState<string>("");
  const [trackingSuggestions, setTrackingSuggestions] = useState<TrackingSuggestion[]>([]);
  const [exportingFormat, setExportingFormat] = useState<ExportFormat | "">("");
  const [exportOptions, setExportOptions] = useState<ExportOptions>({
    include_metadata: true,
    include_reviews: false,
    include_references: false,
    include_drafts: true,
  });
  const [editingChapter, setEditingChapter] = useState<string>("");
  const [savingChapter, setSavingChapter] = useState<string>("");
  const [draftText, setDraftText] = useState("");
  const [outlineVolumeCount, setOutlineVolumeCount] = useState(3);
  const [outlineChaptersPerVolume, setOutlineChaptersPerVolume] = useState(5);
  // 主区当前查看/写作的章节 id。
  const [activeChapter, setActiveChapter] = useState<string>("");
  // 新建项目表单是否展开。
  const [showCreate, setShowCreate] = useState(false);
  const [settingCategory, setSettingCategory] = useState("世界观");
  const [settingKey, setSettingKey] = useState("");
  const [settingValue, setSettingValue] = useState("");
  const [editingSettingId, setEditingSettingId] = useState<string>("");
  const [threadKind, setThreadKind] = useState("foreshadow");
  const [threadStatus, setThreadStatus] = useState("open");
  const [threadTitle, setThreadTitle] = useState("");
  const [threadIntroducedAt, setThreadIntroducedAt] = useState("");
  const [threadDescription, setThreadDescription] = useState("");
  const [threadPayoff, setThreadPayoff] = useState("");
  const [editingThreadId, setEditingThreadId] = useState<string>("");
  const [truthKind, setTruthKind] = useState("constraint");
  const [truthStatus, setTruthStatus] = useState("active");
  const [truthTitle, setTruthTitle] = useState("");
  const [truthScope, setTruthScope] = useState("");
  const [truthOwner, setTruthOwner] = useState("");
  const [truthContent, setTruthContent] = useState("");
  const [editingTruthId, setEditingTruthId] = useState<string>("");
  const [truthCheckResult, setTruthCheckResult] = useState<TruthFileCheckResult | null>(null);
  const [selectedTruthActionKeys, setSelectedTruthActionKeys] = useState<string[]>([]);
  const [referenceText, setReferenceText] = useState("");
  const [referenceFileName, setReferenceFileName] = useState("");
  const [referenceApply, setReferenceApply] = useState(true);
  const [referenceResult, setReferenceResult] = useState<ReferenceAnalyzeResult | null>(null);
  const [referenceVolumeTitle, setReferenceVolumeTitle] = useState("参考拆书");
  const [referenceMaxChapters, setReferenceMaxChapters] = useState(12);
  const [referenceChapterResult, setReferenceChapterResult] = useState<ReferenceChapterImportResult | null>(null);
  const [contextPreview, setContextPreview] = useState<ChapterContextPreview | null>(null);
  const [contextPreviewChapter, setContextPreviewChapter] = useState("");
  const [contextPreviewLoading, setContextPreviewLoading] = useState("");
  const [readerVolumeFilter, setReaderVolumeFilter] = useState("all");
  const [readerStatusFilter, setReaderStatusFilter] = useState("drafted");
  const [readerReviewFilter, setReaderReviewFilter] = useState("all");
  const [readerAiFilter, setReaderAiFilter] = useState("all");
  const [readerKeyword, setReaderKeyword] = useState("");
  const [readerShowOutlines, setReaderShowOutlines] = useState(false);
  const [selectedReaderChapterIds, setSelectedReaderChapterIds] = useState<string[]>([]);

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

  useEffect(() => {
    setSelectedReaderChapterIds([]);
  }, [selected?.id]);

  useEffect(() => {
    if (!selected || !activeChapter || activeChapter === OVERVIEW_ID) {
      setContextPreview(null);
      setContextPreviewChapter("");
      return;
    }
    const entry = selected.volumes
      .flatMap((volume) => volume.chapters.map((chapter) => ({ ch: chapter, vol: volume })))
      .find((item) => item.ch.id === activeChapter);
    if (!entry || isReferenceVolume(entry.vol)) {
      setContextPreview(null);
      setContextPreviewChapter("");
      return;
    }
    let cancelled = false;
    setContextPreviewLoading(activeChapter);
    api.getChapterContextPreview(activeChapter)
      .then((preview) => {
        if (cancelled) return;
        setContextPreview(preview);
        setContextPreviewChapter(activeChapter);
      })
      .catch((e) => {
        if (cancelled) return;
        setContextPreview(null);
        setContextPreviewChapter("");
        setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setContextPreviewLoading("");
      });
    return () => {
      cancelled = true;
    };
  }, [selected, activeChapter]);

  async function open(id: string) {
    setError("");
    try {
      const detail = await api.getProject(id);
      setSelected(detail);
      // 默认进入项目总览；用户选择章节后保持当前章节。
      setActiveChapter((prev) => {
        if (prev === OVERVIEW_ID) return prev;
        const stillExists = detail.volumes.some((v) =>
          v.chapters.some((c) => c.id === prev)
        );
        return stillExists ? prev : OVERVIEW_ID;
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
      await api.generateCharacters(selected.id, 4, activeModel());
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
      await api.generateOutline(selected.id, outlineVolumeCount, outlineChaptersPerVolume, activeModel());
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function fillOutline() {
    if (!selected) return;
    setBusy("outline-fill");
    setError("");
    try {
      await api.fillOutline(selected.id, outlineChaptersPerVolume, activeModel());
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  function activeModel(): string | undefined {
    return model?.trim() || undefined;
  }

  function continuationAnchorOf(project: ProjectDetail | null): ContinuationAnchor | null {
    const value = project?.style_guide?.continuation_anchor;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return value as ContinuationAnchor;
    }
    return null;
  }

  async function setContinuationAnchor(chapterId: string | null) {
    if (!selected) return;
    setBusy("continuation-anchor");
    setError("");
    try {
      await api.updateContinuationAnchor(selected.id, chapterId);
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function reloadContextPreview(chapterId: string) {
    setContextPreviewLoading(chapterId);
    setError("");
    try {
      const preview = await api.getChapterContextPreview(chapterId);
      setContextPreview(preview);
      setContextPreviewChapter(chapterId);
    } catch (e) {
      setContextPreview(null);
      setContextPreviewChapter("");
      setError((e as Error).message);
    } finally {
      setContextPreviewLoading("");
    }
  }

  function resetSettingForm() {
    setEditingSettingId("");
    setSettingCategory("世界观");
    setSettingKey("");
    setSettingValue("");
  }

  function editSetting(setting: WorldSettingOut) {
    setEditingSettingId(setting.id);
    setSettingCategory(setting.category || "世界观");
    setSettingKey(setting.key);
    setSettingValue(setting.value);
  }

  async function saveSetting() {
    if (!selected || !settingKey.trim()) return;
    setBusy("setting");
    setError("");
    try {
      const body = {
        category: settingCategory.trim(),
        key: settingKey.trim(),
        value: settingValue.trim(),
      };
      if (editingSettingId) await api.updateSetting(editingSettingId, body);
      else await api.createSetting(selected.id, body);
      resetSettingForm();
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function deleteSetting(settingId: string) {
    if (!selected) return;
    if (!confirm("确定删除这条设定？")) return;
    setBusy("setting");
    setError("");
    try {
      await api.deleteSetting(settingId);
      if (editingSettingId === settingId) resetSettingForm();
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  function resetThreadForm() {
    setEditingThreadId("");
    setThreadKind("foreshadow");
    setThreadStatus("open");
    setThreadTitle("");
    setThreadIntroducedAt("");
    setThreadDescription("");
    setThreadPayoff("");
  }

  function editThread(item: ForeshadowOut) {
    setEditingThreadId(item.id);
    setThreadKind(item.kind || "foreshadow");
    setThreadStatus(item.status || "open");
    setThreadTitle(item.title);
    setThreadIntroducedAt(item.introduced_at || "");
    setThreadDescription(item.description || "");
    setThreadPayoff(item.payoff || "");
  }

  async function saveThread() {
    if (!selected || !threadTitle.trim()) return;
    setBusy("foreshadow");
    setError("");
    try {
      const body = {
        kind: threadKind,
        status: threadStatus,
        title: threadTitle.trim(),
        introduced_at: threadIntroducedAt.trim(),
        description: threadDescription.trim(),
        payoff: threadPayoff.trim(),
      };
      if (editingThreadId) await api.updateForeshadow(editingThreadId, body);
      else await api.createForeshadow(selected.id, body);
      resetThreadForm();
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function deleteThread(threadId: string) {
    if (!selected) return;
    if (!confirm("确定删除这条伏笔/支线追踪？")) return;
    setBusy("foreshadow");
    setError("");
    try {
      await api.deleteForeshadow(threadId);
      if (editingThreadId === threadId) resetThreadForm();
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  function resetTruthForm() {
    setEditingTruthId("");
    setTruthKind("constraint");
    setTruthStatus("active");
    setTruthTitle("");
    setTruthScope("");
    setTruthOwner("");
    setTruthContent("");
  }

  function editTruthFile(item: TruthFileOut) {
    setEditingTruthId(item.id);
    setTruthKind(item.kind || "constraint");
    setTruthStatus(item.status || "active");
    setTruthTitle(item.title);
    setTruthScope(item.scope || "");
    setTruthOwner(item.owner || "");
    setTruthContent(item.content || "");
  }

  async function saveTruthFile() {
    if (!selected || !truthTitle.trim()) return;
    setBusy("truth-file");
    setError("");
    try {
      const body = {
        kind: truthKind,
        status: truthStatus,
        title: truthTitle.trim(),
        scope: truthScope.trim(),
        owner: truthOwner.trim(),
        content: truthContent.trim(),
      };
      if (editingTruthId) await api.updateTruthFile(editingTruthId, body);
      else await api.createTruthFile(selected.id, body);
      setTruthCheckResult(null);
      setSelectedTruthActionKeys([]);
      resetTruthForm();
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function deleteTruthFile(truthFileId: string) {
    if (!selected) return;
    if (!confirm("确定删除这条真相文件？")) return;
    setBusy("truth-file");
    setError("");
    try {
      await api.deleteTruthFile(truthFileId);
      setTruthCheckResult(null);
      setSelectedTruthActionKeys([]);
      if (editingTruthId === truthFileId) resetTruthForm();
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function checkTruthFiles() {
    if (!selected) return;
    setBusy("truth-check");
    setError("");
    try {
      const result = await api.checkTruthFiles(selected.id, activeModel(), 100);
      setTruthCheckResult(result);
      setSelectedTruthActionKeys(
        result.maintenance_actions
          .map((action, index) => ({ action, index }))
          .filter(({ action }) => canApplyTruthAction(action))
          .map(({ action, index }) => truthActionKey(action, index))
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function applyTruthMaintenanceAction(action: TruthMaintenanceAction) {
    await applyTruthMaintenanceActions([action]);
  }

  function truthActionLogEntry(action: TruthMaintenanceAction): TruthMaintenanceLogEntry {
    return {
      action_type: action.action_type,
      target_type: action.target_type,
      target_id: action.target_id,
      target_title: action.target_title,
      title: action.title || truthActionTypeLabel(action.action_type),
      suggested_status: action.suggested_status || "",
      result: "applied",
      created_at: "",
    };
  }

  async function applyTruthMaintenanceActions(actions: TruthMaintenanceAction[]) {
    if (!selected) return;
    const applicable = actions.filter(canApplyTruthAction);
    if (applicable.length === 0) return;
    setBusy("truth-action");
    setError("");
    try {
      for (const action of applicable) {
        await api.updateTruthFile(action.target_id, { status: action.suggested_status });
      }
      await api.appendTruthMaintenanceLog(selected.id, applicable.map(truthActionLogEntry));
      setTruthCheckResult(null);
      setSelectedTruthActionKeys([]);
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  function toggleTruthActionSelection(key: string) {
    setSelectedTruthActionKeys((items) =>
      items.includes(key) ? items.filter((item) => item !== key) : [...items, key]
    );
  }

  function selectedTruthActions(): TruthMaintenanceAction[] {
    if (!truthCheckResult) return [];
    return truthCheckResult.maintenance_actions.filter((action, index) =>
      canApplyTruthAction(action) && selectedTruthActionKeys.includes(truthActionKey(action, index))
    );
  }

  function setAllTruthActionSelections(selectedAll: boolean) {
    if (!truthCheckResult) return;
    setSelectedTruthActionKeys(
      selectedAll
        ? truthCheckResult.maintenance_actions
            .map((action, index) => ({ action, index }))
            .filter(({ action }) => canApplyTruthAction(action))
            .map(({ action, index }) => truthActionKey(action, index))
        : []
    );
  }

  async function suggestTracking(chapterId: string) {
    setSuggestingChapter(chapterId);
    setError("");
    try {
      const result = await api.suggestTracking(chapterId, activeModel());
      setSuggestionsChapter(chapterId);
      setTrackingSuggestions(result.suggestions);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSuggestingChapter("");
    }
  }

  async function applyTrackingSuggestion(suggestion: TrackingSuggestion) {
    if (!selected || suggestion.suggested_status === "no_change") return;
    setBusy("tracking-apply");
    setError("");
    try {
      await api.updateForeshadow(suggestion.foreshadow_id, {
        status: suggestion.suggested_status,
      });
      setTrackingSuggestions((items) =>
        items.map((item) =>
          item.foreshadow_id === suggestion.foreshadow_id
            ? { ...item, current_status: suggestion.suggested_status }
            : item
        )
      );
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function analyzeReference() {
    if (!selected || referenceText.trim().length < 50) return;
    setBusy("reference");
    setError("");
    try {
      const result = await api.analyzeReference(selected.id, referenceText, referenceApply, activeModel());
      setReferenceResult(result);
      if (referenceApply) await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function importReferenceChapters() {
    if (!selected || referenceText.trim().length < 50) return;
    setBusy("reference-chapters");
    setError("");
    try {
      const result = await api.importReferenceChapters(
        selected.id,
        referenceText,
        referenceVolumeTitle,
        true,
        referenceMaxChapters,
        activeModel()
      );
      setReferenceChapterResult(result);
      await open(selected.id);
      setActiveChapter(OVERVIEW_ID);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function loadReferenceFile(file: File | null) {
    if (!file) return;
    setBusy("reference-file");
    setError("");
    try {
      const text = await file.text();
      setReferenceText(text);
      setReferenceFileName(file.name);
      setReferenceResult(null);
      setReferenceChapterResult(null);
      const baseName = file.name.replace(/\.[^.]+$/, "").trim();
      if (baseName && referenceVolumeTitle.trim() === "参考拆书") {
        setReferenceVolumeTitle(baseName);
      }
    } catch (e) {
      setError(`读取文件失败：${(e as Error).message}`);
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
        { word_count: 1500, model: activeModel() },
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
      await api.reviewChapter(chapterId, activeModel());
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setReviewingChapter("");
    }
  }

  async function reviewSelectedReaderChapters(chapterIds: string[]) {
    if (!selected || chapterIds.length === 0) return;
    setBusy("reader-review");
    setError("");
    try {
      for (const chapterId of chapterIds) {
        setReviewingChapter(chapterId);
        await api.reviewChapter(chapterId, activeModel());
      }
      setSelectedReaderChapterIds([]);
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setReviewingChapter("");
      setBusy("");
    }
  }

  async function reviseChapter(chapterId: string, mode: "fix" | "anti-detect") {
    if (!selected) return;
    setRevisingChapter(chapterId);
    setError("");
    try {
      await api.reviseChapter(chapterId, mode, activeModel());
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRevisingChapter("");
    }
  }

  function startEditChapter(chapterId: string, content = "") {
    setActiveChapter(chapterId);
    setEditingChapter(chapterId);
    setDraftText(content);
  }

  function cancelEditChapter() {
    setEditingChapter("");
    setDraftText("");
  }

  async function saveChapterContent(chapterId: string) {
    if (!selected) return;
    setSavingChapter(chapterId);
    setError("");
    try {
      await api.updateChapterContent(chapterId, draftText, true, activeModel());
      cancelEditChapter();
      await open(selected.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSavingChapter("");
    }
  }

  async function exportProjectFile(format: ExportFormat) {
    if (!selected) return;
    setExportingFormat(format);
    setError("");
    try {
      const { blob, filename } = await api.exportProject(selected.id, format, exportOptions);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || `${selected.title || "novel"}.${format === "epub" ? "epub" : "md"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExportingFormat("");
    }
  }

  function updateExportOption(key: keyof ExportOptions, value: boolean) {
    setExportOptions((options) => ({ ...options, [key]: value }));
  }

  function toggleReaderChapterSelection(chapterId: string) {
    setSelectedReaderChapterIds((items) =>
      items.includes(chapterId) ? items.filter((item) => item !== chapterId) : [...items, chapterId]
    );
  }

  function setAllReaderSelections(chapterIds: string[], selectedAll: boolean) {
    setSelectedReaderChapterIds(selectedAll ? chapterIds : []);
  }

  const officialVolumes = selected?.volumes.filter((v) => !isReferenceVolume(v)) ?? [];
  const referenceVolumes = selected?.volumes.filter(isReferenceVolume) ?? [];
  const allChapters =
    selected?.volumes.flatMap((v) =>
      v.chapters.map((ch) => ({ ch, vol: v }))
    ) ?? [];
  const flatChapters = officialVolumes.flatMap((v) =>
    v.chapters.map((ch) => ({ ch, vol: v }))
  );
  const referenceChapters = referenceVolumes.flatMap((v) =>
    v.chapters.map((ch) => ({ ch, vol: v }))
  );
  type ChapterEntry = (typeof allChapters)[number];
  const activeEntry =
    allChapters.find((e) => e.ch.id === activeChapter) ?? null;
  const draftedCount = flatChapters.filter((e) => e.ch.status === "drafted").length;
  const totalWords = flatChapters.reduce((sum, e) => sum + (e.ch.word_count || 0), 0);
  const allIssues = flatChapters.flatMap((e) => e.ch.review?.issues ?? []);
  const highIssues = allIssues.filter((i) => i.severity === "high").length;
  const mediumIssues = allIssues.filter((i) => i.severity === "medium").length;
  const aiScores = flatChapters
    .map((e) => e.ch.review?.ai_flavor_score)
    .filter((score): score is number => typeof score === "number");
  const avgAiScore = aiScores.length
    ? Math.round(aiScores.reduce((sum, score) => sum + score, 0) / aiScores.length)
    : null;
  const readingChapters = flatChapters.filter((e) => (e.ch.content ?? "").trim());
  const readerKeywordValue = readerKeyword.trim().toLowerCase();
  const readerChapters = flatChapters.filter((entry) => {
    const content = (entry.ch.content ?? "").trim();
    const outline = (entry.ch.outline ?? "").trim();
    const hasContent = Boolean(content);
    const hasReadableOutline = readerShowOutlines && Boolean(outline);
    if (!hasContent && !hasReadableOutline) return false;
    if (readerVolumeFilter !== "all" && entry.vol.id !== readerVolumeFilter) return false;
    if (readerStatusFilter === "drafted" && !hasContent) return false;
    if (readerStatusFilter === "undrafted" && hasContent) return false;
    const reviewSeverity = severityOf(entry.ch.review?.issues);
    if (readerReviewFilter === "unreviewed" && entry.ch.review) return false;
    if (readerReviewFilter === "issues" && (!entry.ch.review || (entry.ch.review.issues ?? []).length === 0)) return false;
    if (["high", "medium", "low", "none"].includes(readerReviewFilter) && reviewSeverity !== readerReviewFilter) return false;
    const aiScore = entry.ch.review?.ai_flavor_score ?? null;
    const aiSeverity = aiSevOf(aiScore);
    if (readerAiFilter !== "all" && aiSeverity !== readerAiFilter) return false;
    if (readerKeywordValue) {
      const haystack = [entry.vol.title, entry.ch.title, entry.ch.outline, entry.ch.summary ?? "", entry.ch.content ?? ""]
        .join("\n")
        .toLowerCase();
      if (!haystack.includes(readerKeywordValue)) return false;
    }
    return true;
  });
  const readerReviewableIds = readerChapters
    .filter((entry) => (entry.ch.content ?? "").trim())
    .map((entry) => entry.ch.id);
  const selectedReaderReviewIds = selectedReaderChapterIds.filter((id) => readerReviewableIds.includes(id));
  const allReaderResultsSelected = readerReviewableIds.length > 0 && selectedReaderReviewIds.length === readerReviewableIds.length;
  const continuationAnchor = continuationAnchorOf(selected);
  const continuationAnchorId = continuationAnchor?.chapter_id ?? "";
  const continuationAnchorEntry = allChapters.find((entry) => entry.ch.id === continuationAnchorId) ?? null;
  const savedStyleStats = styleStatsOf(selected);
  const savedStyleSamples = styleSamplesOf(selected);
  const savedStyleText = styleTextOf(selected);
  const trackingItems = selected?.foreshadows ?? [];
  const truthFiles = selected?.truth_files ?? [];
  const truthMaintenanceLog = truthMaintenanceLogOf(selected);
  const activeTruthFiles = truthFiles.filter((item) => item.status !== "archived");
  const resolvedTruthFiles = truthFiles.filter((item) => item.status === "resolved");
  const unresolvedThreads = trackingItems.filter((item) => item.status !== "resolved").length;
  const resolvedThreads = trackingItems.filter((item) => item.status === "resolved").length;
  const openThreads = trackingItems.filter((item) => item.status === "open").length;
  const progressingThreads = trackingItems.filter((item) => item.status === "progressing").length;
  const staleThreshold = Math.max(3, Math.ceil(flatChapters.length * 0.25));
  const chapterMentions = flatChapters.map((entry, absoluteIndex) => ({
    ...entry,
    absoluteIndex,
  }));
  const trackingAnalysis = trackingItems.map((item) => {
    const needle = item.title.trim().toLowerCase();
    const mentions = needle
      ? chapterMentions.filter(({ ch }) =>
          `${ch.title}\n${ch.outline}\n${ch.content ?? ""}`.toLowerCase().includes(needle)
        )
      : [];
    const lastMention = mentions.length ? mentions[mentions.length - 1] : null;
    const silentChapters = lastMention
      ? Math.max(0, flatChapters.length - lastMention.absoluteIndex - 1)
      : flatChapters.length;
    return {
      item,
      mentions,
      lastMention,
      silentChapters,
      needsAttention:
        item.status !== "resolved" &&
        (mentions.length === 0 || silentChapters >= staleThreshold),
    };
  });
  const staleThreads = trackingAnalysis
    .filter((info) => info.needsAttention)
    .sort((a, b) => b.silentChapters - a.silentChapters);
  const payoffThreads = trackingAnalysis.filter(
    (info) => info.item.status !== "resolved" && info.item.payoff.trim()
  );
  const volumeTrackingStats =
    officialVolumes.map((volume) => {
      const hits = trackingAnalysis.filter((info) =>
        info.mentions.some((mention) => mention.vol.id === volume.id)
      );
      return {
        volume,
        hits,
        unresolvedHits: hits.filter((info) => info.item.status !== "resolved"),
      };
    });

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

  function kindLabel(kind: string): string {
    return (
      {
        foreshadow: "伏笔",
        subplot: "支线",
        resource: "资源线",
        relationship: "情感线",
      }[kind] ?? kind
    );
  }

  function statusLabel(status: string): string {
    return (
      {
        open: "待回收",
        progressing: "推进中",
        resolved: "已回收",
        no_change: "不变",
      }[status] ?? status
    );
  }

  function truthKindLabel(kind: string): string {
    return (
      {
        constraint: "硬约束",
        resource: "资源账本",
        relationship: "关系弧",
        secret: "隐藏真相",
        timeline: "时间锚点",
      }[kind] ?? kind
    );
  }

  function truthStatusLabel(status: string): string {
    return (
      {
        active: "生效中",
        draft: "草稿",
        resolved: "已完成",
        archived: "已归档",
      }[status] ?? status
    );
  }

  function severityLabel(severity: string): string {
    return (
      {
        high: "高风险",
        medium: "中风险",
        low: "低风险",
      }[severity] ?? severity
    );
  }

  function truthConflictSourceLabel(sourceType: string): string {
    return (
      {
        chapter: "章节",
        setting: "设定",
        character: "角色",
        truth_file: "真相文件",
        overview: "项目资料",
      }[sourceType] ?? sourceType
    );
  }

  function truthActionTypeLabel(actionType: string): string {
    return (
      {
        update_truth_status: "更新状态",
        revise_truth_file: "修订真相文件",
        revise_chapter: "修订章节",
        update_setting: "更新设定",
        review_character: "检查角色",
        split_truth_file: "拆分真相文件",
      }[actionType] ?? actionType
    );
  }

  function formatLogTime(value: string): string {
    if (!value) return "刚刚";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function referenceConflictKindLabel(kind: string): string {
    return (
      {
        setting: "设定",
        character: "角色",
        foreshadow: "线索",
      }[kind] ?? kind
    );
  }

  function referenceConflictStatusLabel(status: string): string {
    return status === "conflict" ? "可能冲突" : "重复跳过";
  }

  function contextSourceLabel(sourceType: string): string {
    return (
      {
        setting: "设定",
        character: "角色",
        chapter_summary: "章节摘要",
        volume_outline: "卷纲",
        foreshadow: "线索",
        truth_file: "真相文件",
      }[sourceType] ?? sourceType
    );
  }

  function formatEntityState(state: Record<string, string>): string {
    const parts = Object.entries(state || {})
      .filter(([, value]) => Boolean(value))
      .map(([key, value]) => `${key}=${value}`);
    return parts.join("；") || "暂无细节";
  }

  function jumpToContextSource(chunk: ContextPreviewMemoryChunk) {
    if (chunk.target_type === "chapter" && chunk.target_id) {
      setActiveChapter(chunk.target_id);
    } else if (chunk.target_type === "overview") {
      setActiveChapter(OVERVIEW_ID);
    }
  }

  function jumpToTruthConflictSource(sourceType: string, sourceId: string) {
    if (sourceType === "chapter" && sourceId) {
      setActiveChapter(sourceId);
    } else {
      setActiveChapter(OVERVIEW_ID);
    }
  }

  function clampNumber(value: number, min: number, max: number): number {
    if (Number.isNaN(value)) return min;
    return Math.min(Math.max(value, min), max);
  }

  function isReferenceVolume(volume: VolumeOut): boolean {
    return volume.kind === "reference";
  }

  function chapterRef(entry: ChapterEntry | null): string {
    if (!entry) return "未在卷章中命中";
    return `第 ${entry.vol.order_index + 1} 卷 · ${entry.ch.title}`;
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
              <div className="outline-controls">
                <label>
                  <span>新增卷数</span>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    value={outlineVolumeCount}
                    onChange={(e) =>
                      setOutlineVolumeCount(clampNumber(Number(e.target.value), 1, 12))
                    }
                  />
                </label>
                <label>
                  <span>目标章数/卷</span>
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={outlineChaptersPerVolume}
                    onChange={(e) =>
                      setOutlineChaptersPerVolume(clampNumber(Number(e.target.value), 1, 30))
                    }
                  />
                </label>
              </div>
              <div className="actions">
                <button onClick={genCharacters} disabled={busy !== ""}>
                  {busy === "characters" ? "生成角色中…" : "生成角色"}
                </button>
                <button onClick={genOutline} disabled={busy !== ""}>
                  {busy === "outline"
                    ? "生成大纲中…"
                    : officialVolumes.length > 0
                    ? "追加新卷"
                    : "生成大纲"}
                </button>
                <button
                  className="secondary"
                  onClick={fillOutline}
                  disabled={busy !== "" || officialVolumes.length === 0}
                >
                  {busy === "outline-fill" ? "补齐中…" : "补齐旧卷"}
                </button>
                <button
                  className="secondary"
                  onClick={() => exportProjectFile("markdown")}
                  disabled={exportingFormat !== ""}
                >
                  {exportingFormat === "markdown" ? "导出中…" : "导出 Markdown"}
                </button>
                <button
                  className="secondary"
                  onClick={() => exportProjectFile("epub")}
                  disabled={exportingFormat !== ""}
                >
                  {exportingFormat === "epub" ? "导出中…" : "导出 EPUB"}
                </button>
              </div>
              <div className="export-options">
                <div className="export-options-head">
                  <strong>导出内容</strong>
                  <span>默认导出正文和作品资料</span>
                </div>
                <label>
                  <input
                    type="checkbox"
                    checked={exportOptions.include_metadata}
                    onChange={(e) => updateExportOption("include_metadata", e.target.checked)}
                  />
                  作品资料
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={exportOptions.include_drafts}
                    onChange={(e) => updateExportOption("include_drafts", e.target.checked)}
                  />
                  未成稿大纲
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={exportOptions.include_reviews}
                    onChange={(e) => updateExportOption("include_reviews", e.target.checked)}
                  />
                  审校报告
                </label>
                <label className={referenceVolumes.length === 0 ? "disabled" : ""}>
                  <input
                    type="checkbox"
                    checked={exportOptions.include_references}
                    disabled={referenceVolumes.length === 0}
                    onChange={(e) => updateExportOption("include_references", e.target.checked)}
                  />
                  参考资料{referenceVolumes.length > 0 ? `（${referenceVolumes.length} 组）` : ""}
                </label>
              </div>
            </div>

            <details className="nav-settings" open>
              <summary>设定（{selected.settings.length}）</summary>
              <div className="settings-form">
                <input
                  value={settingCategory}
                  onChange={(e) => setSettingCategory(e.target.value)}
                  placeholder="分类"
                />
                <input
                  value={settingKey}
                  onChange={(e) => setSettingKey(e.target.value)}
                  placeholder="设定名"
                />
                <textarea
                  rows={3}
                  value={settingValue}
                  onChange={(e) => setSettingValue(e.target.value)}
                  placeholder="具体内容"
                />
                <div className="setting-actions">
                  <button
                    className="mini"
                    onClick={saveSetting}
                    disabled={busy === "setting" || !settingKey.trim()}
                  >
                    {editingSettingId ? "保存设定" : "新增设定"}
                  </button>
                  {editingSettingId && (
                    <button className="mini secondary" onClick={resetSettingForm}>
                      取消编辑
                    </button>
                  )}
                </div>
              </div>
              {selected.settings.length === 0 && (
                <div className="hint">暂无设定，新增后会自动注入写作上下文。</div>
              )}
              {selected.settings.map((s) => (
                <div key={s.id} className="setting-card">
                  <div className="setting-title">
                    <strong>{s.key}</strong>
                    {s.category && <span>{s.category}</span>}
                  </div>
                  <div className="meta">{s.value}</div>
                  <div className="setting-actions">
                    <button className="mini secondary" onClick={() => editSetting(s)}>
                      编辑
                    </button>
                    <button className="mini danger" onClick={() => deleteSetting(s.id)}>
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </details>

            <details className="nav-threads" open>
              <summary>伏笔/支线（{trackingItems.length}）</summary>
              <div className="thread-form">
                <div className="thread-form-row">
                  <select value={threadKind} onChange={(e) => setThreadKind(e.target.value)}>
                    <option value="foreshadow">伏笔</option>
                    <option value="subplot">支线</option>
                    <option value="resource">资源线</option>
                    <option value="relationship">情感线</option>
                  </select>
                  <select value={threadStatus} onChange={(e) => setThreadStatus(e.target.value)}>
                    <option value="open">待回收</option>
                    <option value="progressing">推进中</option>
                    <option value="resolved">已回收</option>
                  </select>
                </div>
                <input
                  value={threadTitle}
                  onChange={(e) => setThreadTitle(e.target.value)}
                  placeholder="线索名"
                />
                <input
                  value={threadIntroducedAt}
                  onChange={(e) => setThreadIntroducedAt(e.target.value)}
                  placeholder="引入位置，如 第1卷第3章"
                />
                <textarea
                  rows={3}
                  value={threadDescription}
                  onChange={(e) => setThreadDescription(e.target.value)}
                  placeholder="线索/支线说明"
                />
                <textarea
                  rows={3}
                  value={threadPayoff}
                  onChange={(e) => setThreadPayoff(e.target.value)}
                  placeholder="回收或推进计划"
                />
                <div className="setting-actions">
                  <button
                    className="mini"
                    onClick={saveThread}
                    disabled={busy === "foreshadow" || !threadTitle.trim()}
                  >
                    {editingThreadId ? "保存追踪" : "新增追踪"}
                  </button>
                  {editingThreadId && (
                    <button className="mini secondary" onClick={resetThreadForm}>
                      取消编辑
                    </button>
                  )}
                </div>
              </div>
              {trackingItems.length === 0 && (
                <div className="hint">暂无追踪项，新增后会注入写作、审校和修订上下文。</div>
              )}
              {trackingItems.map((item) => (
                <div key={item.id} className={`thread-card status-${item.status}`}>
                  <div className="thread-card-title">
                    <strong>{item.title}</strong>
                    <span>{kindLabel(item.kind)} · {statusLabel(item.status)}</span>
                  </div>
                  {item.introduced_at && <div className="meta">引入：{item.introduced_at}</div>}
                  {item.description && <div className="meta">说明：{item.description}</div>}
                  {item.payoff && <div className="meta">计划：{item.payoff}</div>}
                  <div className="setting-actions">
                    <button className="mini secondary" onClick={() => editThread(item)}>
                      编辑
                    </button>
                    <button className="mini danger" onClick={() => deleteThread(item.id)}>
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </details>

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

            {officialVolumes.length === 0 && (
              <div className="hint">还没有正文大纲，点上方「生成大纲」。</div>
            )}
            <button
              className={`nav-chapter overview ${activeChapter === OVERVIEW_ID ? "active" : ""}`}
              onClick={() => setActiveChapter(OVERVIEW_ID)}
            >
              <span className="nav-ch-title">总览与阅读</span>
              <span className="nav-ch-badges">{draftedCount}/{flatChapters.length}</span>
            </button>
            {officialVolumes.map((v: VolumeOut) => (
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
            {referenceVolumes.length > 0 && (
              <details className="nav-reference" open>
                <summary>参考资料（{referenceChapters.length}章）</summary>
                <div className="hint">拆书导入的原文，只供分析、检索和续写起点使用。</div>
                {referenceVolumes.map((v: VolumeOut) => (
                  <div key={v.id} className="nav-vol reference">
                    <div className="nav-vol-title" title={v.outline}>
                      {v.title}
                    </div>
                    <ul className="nav-chapters">
                      {v.chapters.map((ch) => {
                        const isActive = ch.id === activeChapter;
                        const isAnchor = continuationAnchorId === ch.id;
                        return (
                          <li key={ch.id}>
                            <button
                              className={`nav-chapter reference ${isActive ? "active" : ""}`}
                              onClick={() => setActiveChapter(ch.id)}
                            >
                              <span className="nav-ch-title">{ch.title}</span>
                              <span className="nav-ch-badges">
                                {isAnchor ? <span className="dot anchor" /> : <span className="dot reference" />}
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </details>
            )}
          </>
        )}
      </nav>

      {/* 右栏：正文主区 */}
      <main className="main-pane">
        {error && <div className="error">错误：{error}</div>}
        {!selected ? (
          <div className="hint center">从左侧选择项目开始创作。</div>
        ) : activeChapter === OVERVIEW_ID ? (
          <article className="project-overview">
            <header className="chapter-head">
              <div className="crumbs">项目总览</div>
              <h2>{selected.title}</h2>
              <div className="chapter-outline">{selected.premise || "暂无一句话设定"}</div>
            </header>

            <section className="stats-grid">
              <div className="stat-box">
                <span>总字数</span>
                <strong>{totalWords}</strong>
              </div>
              <div className="stat-box">
                <span>章节进度</span>
                <strong>
                  {draftedCount}/{flatChapters.length || 0}
                </strong>
              </div>
              <div className="stat-box">
                <span>参考资料</span>
                <strong>{referenceChapters.length}</strong>
                <small>{referenceVolumes.length} 组 · 不计入正文</small>
              </div>
              <div className="stat-box">
                <span>审校问题</span>
                <strong>{allIssues.length}</strong>
                <small>高 {highIssues} · 中 {mediumIssues}</small>
              </div>
              <div className="stat-box">
                <span>AI味均分</span>
                <strong>{avgAiScore ?? "-"}</strong>
              </div>
              <div className="stat-box">
                <span>线索追踪</span>
                <strong>{unresolvedThreads}/{trackingItems.length}</strong>
                <small>已回收 {resolvedThreads}</small>
              </div>
              <div className="stat-box">
                <span>真相文件</span>
                <strong>{activeTruthFiles.length}</strong>
                <small>已完成 {resolvedTruthFiles.length}</small>
              </div>
            </section>

            <section className="overview-section">
              <h3>续写起点</h3>
              {!continuationAnchorId ? (
                <div className="hint">打开任意已成稿正文或参考章节，可将其设为续写起点。</div>
              ) : (
                <div className="continuation-anchor-card">
                  <div>
                    <strong>
                      {continuationAnchorEntry
                        ? chapterRef(continuationAnchorEntry)
                        : continuationAnchor?.chapter_title || "已设置的章节"}
                    </strong>
                    <div className="meta">
                      生成正文新章时会注入该章节的结尾、摘要和实体状态。
                    </div>
                  </div>
                  <button
                    className="mini secondary"
                    disabled={busy === "continuation-anchor"}
                    onClick={() => setContinuationAnchor(null)}
                  >
                    清除
                  </button>
                </div>
              )}
            </section>

            <section className="overview-section">
              <h3>拆书与文风</h3>
              {(savedStyleText || savedStyleStats || savedStyleSamples.length > 0) ? (
                <div className="style-profile-card">
                  <div className="style-profile-head">
                    <div>
                      <strong>当前文风指纹</strong>
                      {savedStyleText ? (
                        <p>{savedStyleText.split("\n").filter(Boolean).slice(0, 4).join(" ")}</p>
                      ) : (
                        <p>已保存本地统计约束。</p>
                      )}
                    </div>
                    <span>{savedStyleStats ? `${savedStyleStats.sample_chars} 字样本` : `${savedStyleSamples.length} 段样例`}</span>
                  </div>
                  {savedStyleStats && <StyleStatsPanel stats={savedStyleStats} />}
                  <StyleSamplesPanel samples={savedStyleSamples} />
                </div>
              ) : (
                <div className="hint">导入或分析参考文本后会生成文风指纹。</div>
              )}
              <div className="reference-import">
                <div className="reference-explainer">
                  <div>
                    <strong>分析资料</strong>
                    <span>抽取文风、设定、角色和线索，可写入项目资料。</span>
                  </div>
                  <div>
                    <strong>按章导入为参考资料</strong>
                    <span>原文按章节保存到左侧“参考资料”，不改写、不计入正文进度、不默认导出。</span>
                  </div>
                  <div>
                    <strong>续写起点</strong>
                    <span>打开参考章节或正文章节后，可指定从这一章后面继续写。</span>
                  </div>
                </div>
                <div className="reference-source-row">
                  <label className="reference-file-control">
                    <span>导入文本文件</span>
                    <input
                      type="file"
                      accept=".txt,.md,.markdown,text/plain,text/markdown"
                      disabled={busy !== ""}
                      onChange={(e) => {
                        loadReferenceFile(e.target.files?.[0] ?? null);
                        e.target.value = "";
                      }}
                    />
                  </label>
                  <span className="reference-file-name">
                    {busy === "reference-file"
                      ? "读取中…"
                      : referenceFileName || "也可以直接在下方粘贴片段"}
                  </span>
                </div>
                <textarea
                  rows={8}
                  value={referenceText}
                  onChange={(e) => setReferenceText(e.target.value)}
                  placeholder="粘贴参考文本，或先导入 .txt / .md 文件"
                />
                <div className="reference-import-options">
                  <label>
                    <span>参考资料名称</span>
                    <input
                      value={referenceVolumeTitle}
                      onChange={(e) => setReferenceVolumeTitle(e.target.value)}
                    />
                    <small>导入后在左侧“参考资料”里显示的名称</small>
                  </label>
                  <label>
                    <span>最多导入章节</span>
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={referenceMaxChapters}
                      onChange={(e) =>
                        setReferenceMaxChapters(clampNumber(Number(e.target.value), 1, 30))
                      }
                    />
                    <small>防止一次导入过多章节</small>
                  </label>
                </div>
                <div className="reference-actions">
                  <label>
                    <input
                      type="checkbox"
                      checked={referenceApply}
                      onChange={(e) => setReferenceApply(e.target.checked)}
                    />
                    分析后写入设定/角色/线索
                  </label>
                  <div className="reference-action-buttons">
                    <button
                      className="gen"
                      disabled={busy !== "" || referenceText.trim().length < 50}
                      onClick={analyzeReference}
                    >
                      {busy === "reference" ? "分析中…" : referenceApply ? "分析并写入资料" : "仅分析"}
                    </button>
                    <button
                      className="secondary"
                      disabled={busy !== "" || referenceText.trim().length < 50}
                      onClick={importReferenceChapters}
                    >
                      {busy === "reference-chapters" ? "导入中…" : "按章导入为参考资料"}
                    </button>
                  </div>
                </div>
                {referenceResult && (
                  <div className="reference-result">
                    <div className="tracking-metric-row">
                      <span>写入</span>
                      <strong>{referenceResult.applied ? "已写入" : "未写入"}</strong>
                    </div>
                    {referenceResult.applied && (
                      <div className="reference-counts">
                        <span>设定 {referenceResult.created_counts.settings ?? 0}</span>
                        <span>角色 {referenceResult.created_counts.characters ?? 0}</span>
                        <span>线索 {referenceResult.created_counts.foreshadows ?? 0}</span>
                        <span>重复 {referenceResult.created_counts.duplicates ?? 0}</span>
                        <span>冲突 {referenceResult.created_counts.conflicts ?? 0}</span>
                      </div>
                    )}
                    {(referenceResult.conflicts ?? []).length > 0 && (
                      <div className="reference-conflicts">
                        <strong>写入检查</strong>
                        <div className="meta">重复项会自动跳过；可能冲突的内容不会自动覆盖已有资料。</div>
                        {(referenceResult.conflicts ?? []).slice(0, 8).map((item: ReferenceConflictItem, idx: number) => (
                          <div key={`${item.kind}-${item.name}-${idx}`} className={`reference-conflict ${item.status}`}>
                            <div className="thread-card-title">
                              <strong>{referenceConflictKindLabel(item.kind)} · {item.name}</strong>
                              <span>{referenceConflictStatusLabel(item.status)}</span>
                            </div>
                            <div className="meta">{item.detail}</div>
                            {item.existing && <div className="meta">已有：{item.existing}</div>}
                            {item.incoming && <div className="meta">导入：{item.incoming}</div>}
                          </div>
                        ))}
                        {referenceResult.conflicts.length > 8 && (
                          <div className="meta">还有 {referenceResult.conflicts.length - 8} 项未展开。</div>
                        )}
                      </div>
                    )}
                    <div className="reference-style">
                      <strong>文风指纹</strong>
                      <p>{referenceResult.style_fingerprint.summary || "暂无摘要"}</p>
                      {referenceResult.style_fingerprint.sentence_rhythm && (
                        <p>节奏：{referenceResult.style_fingerprint.sentence_rhythm}</p>
                      )}
                      {referenceResult.style_fingerprint.dialogue && (
                        <p>对白：{referenceResult.style_fingerprint.dialogue}</p>
                      )}
                      {referenceResult.style_stats?.sample_chars > 0 && (
                        <StyleStatsPanel stats={referenceResult.style_stats} compact />
                      )}
                      <StyleSamplesPanel samples={referenceResult.style_samples ?? []} compact />
                    </div>
                    <div className="reference-preview-grid">
                      <div>
                        <strong>设定</strong>
                        {referenceResult.settings.slice(0, 4).map((item, idx) => (
                          <div key={idx} className="meta">{item.category ? `[${item.category}] ` : ""}{item.key}</div>
                        ))}
                      </div>
                      <div>
                        <strong>角色</strong>
                        {referenceResult.characters.slice(0, 4).map((item) => (
                          <div key={item.name} className="meta">{item.name}</div>
                        ))}
                      </div>
                      <div>
                        <strong>线索</strong>
                        {referenceResult.foreshadows.slice(0, 4).map((item) => (
                          <div key={item.title} className="meta">{item.title}</div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
                {referenceChapterResult && (
                  <div className="reference-result">
                    <div className="tracking-metric-row">
                      <span>参考资料</span>
                      <strong>{referenceChapterResult.volume_title}</strong>
                    </div>
                    <div className="meta">已按原文保存，不会计入正文进度或导出。</div>
                    <div className="reference-counts">
                      <span>章节 {referenceChapterResult.imported_chapters}</span>
                      <span>时间线 {referenceChapterResult.timeline.length}</span>
                      {referenceChapterResult.style_stats?.sample_chars > 0 && (
                        <span>文风样本 {referenceChapterResult.style_stats.sample_chars} 字</span>
                      )}
                    </div>
                    {referenceChapterResult.style_stats?.sample_chars > 0 && (
                      <StyleStatsPanel stats={referenceChapterResult.style_stats} compact />
                    )}
                    <StyleSamplesPanel samples={referenceChapterResult.style_samples ?? []} compact />
                    <div className="reference-timeline">
                      {referenceChapterResult.timeline.slice(0, 6).map((item) => (
                        <div key={item.chapter_id} className="reference-timeline-item">
                          <strong>{item.order_index + 1}. {item.title}</strong>
                          {item.summary && <p>{item.summary}</p>}
                          <div className="meta">
                            角色状态 {Object.keys(item.entity_states).length} · 关键词 {item.keywords.slice(0, 5).join("、") || "无"}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </section>

            <section className="overview-section">
              <h3>卷章进度</h3>
              {officialVolumes.length === 0 ? (
                <div className="hint">生成正文大纲后会显示卷章进度。参考资料不会计入这里。</div>
              ) : (
                officialVolumes.map((v) => {
                  const words = v.chapters.reduce((sum, ch) => sum + (ch.word_count || 0), 0);
                  const drafted = v.chapters.filter((ch) => ch.status === "drafted").length;
                  return (
                    <div key={v.id} className="volume-progress">
                      <div>
                        <strong>第 {v.order_index + 1} 卷 · {v.title}</strong>
                        <span>{drafted}/{v.chapters.length} 章 · {words} 字</span>
                      </div>
                      <progress value={drafted} max={Math.max(v.chapters.length, 1)} />
                    </div>
                  );
                })
              )}
            </section>

            <section className="overview-section">
              <h3>真相文件</h3>
              <details className="truth-guide" open={truthFiles.length === 0}>
                <summary>这是什么，什么时候用？</summary>
                <div className="truth-guide-body">
                  <p>
                    真相文件是作者视角的长期事实库，用来记录后文不能写崩的秘密、规则、资源和关系变化。它会参与大纲、写作、审校和修订，但不会自动变成正文，也不会原封不动写进章节。
                  </p>
                  <div className="truth-guide-grid">
                    <div>
                      <strong>和伏笔的区别</strong>
                      <span>伏笔是读者能看到的线索；真相文件是作者知道、模型必须遵守的底层事实。</span>
                    </div>
                    <div>
                      <strong>先填哪三类</strong>
                      <span>主角能力限制、暂时不能公开的核心秘密、重要关系的真实走向。</span>
                    </div>
                    <div>
                      <strong>怎么检查</strong>
                      <span>点击“检查矛盾”会扫描设定、角色和正文卷章，给出证据、来源和维护建议。</span>
                    </div>
                  </div>
                  <div className="truth-guide-example">
                    <strong>例子</strong>
                    <span>事实：完整封门剑只能使用 3 次，运动会已用掉 1 次。限制：第 2 次必须留给地铁阵眼。影响：中途战斗不能随便让主角开大解决问题。</span>
                  </div>
                </div>
              </details>
              <div className="truth-explainer">
                <div>
                  <strong>长期事实</strong>
                  <span>记录不能被后文写崩的规则、秘密、资源和关系变化。</span>
                </div>
                <div>
                  <strong>生成约束</strong>
                  <span>写大纲、写章节、审校和修订时会作为背景资料注入。</span>
                </div>
                <div>
                  <strong>不是正文</strong>
                  <span>这里的内容不会自动变成章节，也不会原封不动写进正文。</span>
                </div>
              </div>
              <div className="truth-editor">
                <div className="truth-form-grid">
                  <label>
                    <span>类型</span>
                    <select
                      value={truthKind}
                      title="选择这条长期事实最接近的用途；不确定时选硬约束。"
                      onChange={(e) => setTruthKind(e.target.value)}
                    >
                      <option value="constraint">硬约束</option>
                      <option value="resource">资源账本</option>
                      <option value="relationship">关系弧</option>
                      <option value="secret">隐藏真相</option>
                      <option value="timeline">时间锚点</option>
                    </select>
                  </label>
                  <label>
                    <span>状态</span>
                    <select
                      value={truthStatus}
                      title="生效中会参与生成和检查；草稿用于未定想法；已归档不会参与生成。"
                      onChange={(e) => setTruthStatus(e.target.value)}
                    >
                      <option value="active">生效中</option>
                      <option value="draft">草稿</option>
                      <option value="resolved">已完成</option>
                      <option value="archived">已归档</option>
                    </select>
                  </label>
                  <label>
                    <span>标题</span>
                    <input
                      value={truthTitle}
                      onChange={(e) => setTruthTitle(e.target.value)}
                      placeholder="例如：主角的真实债务"
                      title="短一点，方便以后在检查结果和导出资料里识别。"
                    />
                    <small>给这条长期事实起一个短名。</small>
                  </label>
                  <label>
                    <span>范围</span>
                    <input
                      value={truthScope}
                      onChange={(e) => setTruthScope(e.target.value)}
                      placeholder="整书 / 第2卷 / 某角色线"
                      title="说明这条事实影响全书、某一卷，还是某条角色/支线。"
                    />
                    <small>它影响哪里。</small>
                  </label>
                  <label>
                    <span>负责人/相关人</span>
                    <input
                      value={truthOwner}
                      onChange={(e) => setTruthOwner(e.target.value)}
                      placeholder="角色、势力或道具"
                      title="写角色、组织、道具、地点或势力，方便检索和检查。"
                    />
                    <small>和谁或什么有关。</small>
                  </label>
                </div>
                <textarea
                  rows={4}
                  value={truthContent}
                  onChange={(e) => setTruthContent(e.target.value)}
                  placeholder="写清楚事实、限制、变化条件、什么时候能揭露。"
                  title="建议包含：已确定事实、揭露/变化条件、正文必须遵守的限制。"
                />
                <div className="truth-writing-tip">
                  建议写法：事实是什么；什么时候之前不能改或不能揭露；正文涉及它时必须遵守什么限制。
                </div>
                <div className="truth-actions">
                  <button
                    className="gen"
                    disabled={busy === "truth-file" || !truthTitle.trim()}
                    onClick={saveTruthFile}
                  >
                    {busy === "truth-file" ? "保存中…" : editingTruthId ? "保存修改" : "新增真相文件"}
                  </button>
                  {editingTruthId && (
                    <button className="secondary" disabled={busy === "truth-file"} onClick={resetTruthForm}>
                      取消编辑
                    </button>
                  )}
                </div>
              </div>

              <div className="truth-check-panel">
                <div className="truth-check-head">
                  <div>
                    <strong>一致性检查</strong>
                    <span>扫描真相文件与设定、角色、正文卷章之间的明显冲突。</span>
                  </div>
                  <button
                    className="gen secondary"
                    disabled={busy !== "" || activeTruthFiles.length === 0}
                    onClick={checkTruthFiles}
                  >
                    {busy === "truth-check" ? "检查中…" : "检查矛盾"}
                  </button>
                </div>
                {truthCheckResult && (
                  <div className="truth-check-result">
                    <div className="reference-counts">
                      <span>真相 {truthCheckResult.checked_truth_files}</span>
                      <span>章节 {truthCheckResult.checked_chapters}</span>
                      <span>问题 {truthCheckResult.issues.length}</span>
                      <span>建议 {truthCheckResult.maintenance_actions.length}</span>
                    </div>
                    {truthCheckResult.issues.length === 0 ? (
                      <div className="hint">未发现明确矛盾。</div>
                    ) : (
                      <div className="truth-conflict-list">
                        {truthCheckResult.issues.map((issue, idx) => (
                          <article key={`${issue.truth_file_id}-${issue.source_id}-${idx}`} className={`truth-conflict-card sev-${issue.severity}`}>
                            <div className="thread-card-title">
                              <strong>{issue.truth_title}</strong>
                              <span>{severityLabel(issue.severity)}</span>
                            </div>
                            <div className="meta">
                              来源：{truthConflictSourceLabel(issue.source_type)} · {issue.source_title || "未命名资料"}
                            </div>
                            {issue.evidence && <p>证据：{issue.evidence}</p>}
                            {issue.description && <p>问题：{issue.description}</p>}
                            {issue.suggestion && <p>建议：{issue.suggestion}</p>}
                            <button
                              className="mini secondary"
                              onClick={() => jumpToTruthConflictSource(issue.source_type, issue.source_id)}
                            >
                              跳转来源
                            </button>
                          </article>
                        ))}
                      </div>
                    )}
                    {truthCheckResult.maintenance_actions.length > 0 && (
                      <div className="truth-maintenance-list">
                        {(() => {
                          const applicableCount = truthCheckResult.maintenance_actions.filter(canApplyTruthAction).length;
                          const selectedActions = selectedTruthActions();
                          const allSelected = applicableCount > 0 && selectedActions.length === applicableCount;
                          return (
                            <>
                              <div className="truth-maintenance-head">
                                <strong>维护建议</strong>
                                {applicableCount > 0 && (
                                  <div className="truth-batch-actions">
                                    <label>
                                      <input
                                        type="checkbox"
                                        checked={allSelected}
                                        onChange={(e) => setAllTruthActionSelections(e.target.checked)}
                                      />
                                      全选可应用
                                    </label>
                                    <button
                                      className="mini secondary"
                                      disabled={busy === "truth-action" || selectedActions.length === 0}
                                      onClick={() => applyTruthMaintenanceActions(selectedActions)}
                                    >
                                      {busy === "truth-action" ? "应用中…" : `应用已选 ${selectedActions.length}`}
                                    </button>
                                  </div>
                                )}
                              </div>
                              {truthCheckResult.maintenance_actions.map((action, idx) => {
                                const canApplyStatus = canApplyTruthAction(action);
                                const actionKey = truthActionKey(action, idx);
                                return (
                                  <article key={`${action.action_type}-${action.target_id}-${idx}`} className={`truth-maintenance-card sev-${action.priority}`}>
                                    <div className="thread-card-title">
                                      <div className="truth-maintenance-title">
                                        {canApplyStatus && (
                                          <input
                                            type="checkbox"
                                            checked={selectedTruthActionKeys.includes(actionKey)}
                                            onChange={() => toggleTruthActionSelection(actionKey)}
                                            title="加入批量应用"
                                          />
                                        )}
                                        <strong>{action.title || truthActionTypeLabel(action.action_type)}</strong>
                                      </div>
                                      <span>{severityLabel(action.priority)}</span>
                                    </div>
                                    <div className="meta">
                                      {truthActionTypeLabel(action.action_type)} · {truthConflictSourceLabel(action.target_type)} · {action.target_title || "未命名目标"}
                                    </div>
                                    {action.reason && <p>原因：{action.reason}</p>}
                                    {action.suggestion && <p>建议：{action.suggestion}</p>}
                                    {action.suggested_status && <p>建议状态：{truthStatusLabel(action.suggested_status)}</p>}
                                    <div className="truth-card-actions">
                                      <button
                                        className="mini secondary"
                                        onClick={() => jumpToTruthConflictSource(action.target_type, action.target_id)}
                                      >
                                        跳转目标
                                      </button>
                                      {canApplyStatus && (
                                        <button
                                          className="mini secondary"
                                          disabled={busy === "truth-action"}
                                          onClick={() => applyTruthMaintenanceAction(action)}
                                        >
                                          {busy === "truth-action" ? "应用中…" : "应用状态"}
                                        </button>
                                      )}
                                    </div>
                                  </article>
                                );
                              })}
                            </>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {truthMaintenanceLog.length > 0 && (
                <div className="truth-log-panel">
                  <div className="truth-log-head">
                    <strong>最近处理记录</strong>
                    <span>只记录你应用过的维护动作，方便回看。</span>
                  </div>
                  <div className="truth-log-list">
                    {truthMaintenanceLog.slice(0, 6).map((entry, idx) => (
                      <div key={`${entry.created_at}-${entry.target_id}-${idx}`} className="truth-log-item">
                        <div>
                          <strong>{entry.title || truthActionTypeLabel(entry.action_type)}</strong>
                          <span>{truthActionTypeLabel(entry.action_type)} · {entry.target_title || "未命名目标"}</span>
                        </div>
                        <div>
                          {entry.suggested_status && <span>状态：{truthStatusLabel(entry.suggested_status)}</span>}
                          <small>{formatLogTime(entry.created_at)}</small>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {truthFiles.length === 0 ? (
                <div className="hint">还没有真相文件。适合先放“不能改的设定”和“暂不揭露的秘密”。</div>
              ) : (
                <div className="truth-file-board">
                  {truthFiles.map((item) => (
                    <article key={item.id} className={`truth-file-card status-${item.status}`}>
                      <div className="thread-card-title">
                        <strong>{item.title}</strong>
                        <span>{truthKindLabel(item.kind)} · {truthStatusLabel(item.status)}</span>
                      </div>
                      {(item.scope || item.owner) && (
                        <div className="meta">
                          {item.scope ? `范围：${item.scope}` : ""}
                          {item.scope && item.owner ? " · " : ""}
                          {item.owner ? `相关：${item.owner}` : ""}
                        </div>
                      )}
                      {item.content && <p>{item.content}</p>}
                      <div className="truth-card-actions">
                        <button className="mini secondary" onClick={() => editTruthFile(item)}>编辑</button>
                        <button className="mini secondary" onClick={() => deleteTruthFile(item.id)}>删除</button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section className="overview-section">
              <h3>伏笔与支线</h3>
              {trackingItems.length === 0 ? (
                <div className="hint">还没有登记伏笔、支线或资源线。</div>
              ) : (
                <>
                  <div className="tracking-dashboard">
                    <div className="tracking-panel">
                      <h4>状态分布</h4>
                      <div className="tracking-metric-row">
                        <span>待回收</span>
                        <strong>{openThreads}</strong>
                      </div>
                      <div className="tracking-metric-row">
                        <span>推进中</span>
                        <strong>{progressingThreads}</strong>
                      </div>
                      <div className="tracking-metric-row">
                        <span>已回收</span>
                        <strong>{resolvedThreads}</strong>
                      </div>
                    </div>

                    <div className="tracking-panel">
                      <h4>跨卷命中</h4>
                      {volumeTrackingStats.length === 0 ? (
                        <div className="hint">生成大纲后会显示各卷命中情况。</div>
                      ) : (
                        volumeTrackingStats.map(({ volume, hits, unresolvedHits }) => (
                          <div key={volume.id} className="tracking-metric-row">
                            <span>第 {volume.order_index + 1} 卷</span>
                            <strong>{hits.length}</strong>
                            <small>未完 {unresolvedHits.length}</small>
                          </div>
                        ))
                      )}
                    </div>

                    <div className="tracking-panel">
                      <h4>需要关注</h4>
                      {staleThreads.length === 0 ? (
                        <div className="hint">暂无长时间沉默的未回收线索。</div>
                      ) : (
                        staleThreads.slice(0, 5).map(({ item, mentions, silentChapters }) => (
                          <div key={item.id} className="tracking-alert-row">
                            <strong>{item.title}</strong>
                            <span>{mentions.length === 0 ? "未在卷章中命中" : `已沉默 ${silentChapters} 章`}</span>
                          </div>
                        ))
                      )}
                    </div>

                    <div className="tracking-panel">
                      <h4>回收计划</h4>
                      {payoffThreads.length === 0 ? (
                        <div className="hint">暂无待执行的回收计划。</div>
                      ) : (
                        payoffThreads.slice(0, 5).map(({ item }) => (
                          <div key={item.id} className="tracking-alert-row">
                            <strong>{item.title}</strong>
                            <span>{item.payoff}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="thread-board">
                    {trackingAnalysis.map(({ item, mentions, lastMention, silentChapters }) => (
                      <article key={item.id} className={`thread-card status-${item.status}`}>
                        <div className="thread-card-title">
                          <strong>{item.title}</strong>
                          <span>{kindLabel(item.kind)} · {statusLabel(item.status)}</span>
                        </div>
                        <div className="meta">
                          命中 {mentions.length} 处 · 最后：{chapterRef(lastMention)}
                          {item.status !== "resolved" && mentions.length > 0 ? ` · 沉默 ${silentChapters} 章` : ""}
                        </div>
                        {item.introduced_at && <div className="meta">引入：{item.introduced_at}</div>}
                        {item.description && <div className="meta">说明：{item.description}</div>}
                        {item.payoff && <div className="meta">计划：{item.payoff}</div>}
                      </article>
                    ))}
                  </div>
                </>
              )}
            </section>

            <section className="overview-section">
              <h3>整书大纲</h3>
              {officialVolumes.length === 0 ? (
                <div className="hint">生成正文大纲后会显示整书卷纲与章纲。</div>
              ) : (
                <div className="book-outline">
                  {officialVolumes.map((v) => (
                    <section key={v.id} className="outline-volume">
                      <h4>第 {v.order_index + 1} 卷 · {v.title}</h4>
                      {v.outline && <p>{v.outline}</p>}
                      <ol className="outline-chapters">
                        {v.chapters.map((ch) => (
                          <li key={ch.id}>
                            <strong>{ch.title}</strong>
                            <span>{ch.outline}</span>
                          </li>
                        ))}
                      </ol>
                    </section>
                  ))}
                </div>
              )}
            </section>

            <section className="overview-section">
              <h3>整书阅读</h3>
              {flatChapters.length === 0 ? (
                <div className="hint">还没有成稿章节。</div>
              ) : (
                <div className="reader-workbench">
                  <div className="reader-filter-bar">
                    <label>
                      <span>卷</span>
                      <select value={readerVolumeFilter} onChange={(e) => setReaderVolumeFilter(e.target.value)}>
                        <option value="all">全部正文卷</option>
                        {officialVolumes.map((volume) => (
                          <option key={volume.id} value={volume.id}>第 {volume.order_index + 1} 卷 · {volume.title}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>状态</span>
                      <select value={readerStatusFilter} onChange={(e) => setReaderStatusFilter(e.target.value)}>
                        <option value="drafted">已成稿</option>
                        <option value="undrafted">未成稿</option>
                        <option value="all">全部</option>
                      </select>
                    </label>
                    <label>
                      <span>审校</span>
                      <select value={readerReviewFilter} onChange={(e) => setReaderReviewFilter(e.target.value)}>
                        <option value="all">不限</option>
                        <option value="unreviewed">未审校</option>
                        <option value="issues">有问题</option>
                        <option value="high">高风险</option>
                        <option value="medium">中风险</option>
                        <option value="low">低风险</option>
                        <option value="none">无问题</option>
                      </select>
                    </label>
                    <label>
                      <span>AI 味</span>
                      <select value={readerAiFilter} onChange={(e) => setReaderAiFilter(e.target.value)}>
                        <option value="all">不限</option>
                        <option value="high">高</option>
                        <option value="medium">中</option>
                        <option value="low">低</option>
                        <option value="none">未评分</option>
                      </select>
                    </label>
                    <label className="reader-search">
                      <span>搜索</span>
                      <input
                        value={readerKeyword}
                        onChange={(e) => setReaderKeyword(e.target.value)}
                        placeholder="标题 / 大纲 / 正文"
                      />
                    </label>
                    <label className="reader-toggle">
                      <input
                        type="checkbox"
                        checked={readerShowOutlines}
                        onChange={(e) => {
                          setReaderShowOutlines(e.target.checked);
                          if (e.target.checked && readerStatusFilter === "drafted") setReaderStatusFilter("all");
                        }}
                      />
                      显示未成稿大纲
                    </label>
                  </div>
                  <div className="reader-batch-bar">
                    <div>
                      <strong>{readerChapters.length}</strong>
                      <span> 条结果 · 已成稿 {readingChapters.length}/{flatChapters.length}</span>
                    </div>
                    <div className="reader-batch-actions">
                      <label>
                        <input
                          type="checkbox"
                          checked={allReaderResultsSelected}
                          disabled={readerReviewableIds.length === 0}
                          onChange={(e) => setAllReaderSelections(readerReviewableIds, e.target.checked)}
                        />
                        选择当前可审校章节
                      </label>
                      <button
                        className="mini secondary"
                        disabled={busy === "reader-review" || selectedReaderReviewIds.length === 0 || writingChapter !== ""}
                        onClick={() => reviewSelectedReaderChapters(selectedReaderReviewIds)}
                      >
                        {busy === "reader-review" ? "批量审校中…" : `批量重审 ${selectedReaderReviewIds.length}`}
                      </button>
                      <button
                        className="mini secondary"
                        disabled={selectedReaderChapterIds.length === 0 || busy === "reader-review"}
                        onClick={() => setSelectedReaderChapterIds([])}
                      >
                        清空选择
                      </button>
                    </div>
                  </div>
                  {readerChapters.length === 0 ? (
                    <div className="hint">当前筛选没有匹配章节。可以调整状态、搜索词，或打开“显示未成稿大纲”。</div>
                  ) : (
                    <div className="book-reader">
                      {readerChapters.map(({ ch, vol }) => {
                        const content = (ch.content ?? "").trim();
                        const review = ch.review;
                        const issueSeverity = severityOf(review?.issues);
                        const aiScore = review?.ai_flavor_score ?? null;
                        const aiSeverity = aiSevOf(aiScore);
                        const reviewable = Boolean(content);
                        const selectedForBatch = selectedReaderChapterIds.includes(ch.id);
                        return (
                          <section key={ch.id} className="reader-chapter">
                            <div className="reader-chapter-head">
                              <label className={!reviewable ? "disabled" : ""}>
                                <input
                                  type="checkbox"
                                  checked={selectedForBatch}
                                  disabled={!reviewable || busy === "reader-review"}
                                  onChange={() => toggleReaderChapterSelection(ch.id)}
                                />
                                批量
                              </label>
                              <div>
                                <div className="crumbs">第 {vol.order_index + 1} 卷 · {vol.title}</div>
                                <h4>{ch.title}</h4>
                              </div>
                              <div className="reader-badges">
                                <span className={`badge ${content ? "drafted" : ""}`}>{content ? `${ch.word_count}字` : "未成稿"}</span>
                                {review && <span className={`badge review sev-${issueSeverity}`}>{review.issues.length === 0 ? "审校通过" : `${review.issues.length} 问题`}</span>}
                                {review && aiScore !== null && <span className={`badge review sev-${aiSeverity}`}>AI味 {aiScore}</span>}
                              </div>
                            </div>
                            <div className="reader-card-actions">
                              <button className="mini secondary" onClick={() => setActiveChapter(ch.id)}>打开章节</button>
                              {reviewable && (
                                <button
                                  className="mini secondary"
                                  disabled={busy === "reader-review" || reviewingChapter === ch.id || writingChapter !== ""}
                                  onClick={() => reviewChapter(ch.id)}
                                >
                                  {reviewingChapter === ch.id ? "审校中…" : "重新审校"}
                                </button>
                              )}
                            </div>
                            <div className={content ? "output" : "reader-outline-output"}>
                              {content || ch.outline || "暂无大纲"}
                            </div>
                          </section>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </section>
          </article>
        ) : !activeEntry ? (
          <div className="hint center">生成大纲后，从中间选择章节。</div>
        ) : (
          (() => {
            const { ch, vol } = activeEntry;
            const isReference = isReferenceVolume(vol);
            const drafted = ch.status === "drafted";
            const isWriting = writingChapter === ch.id;
            const isReviewing = reviewingChapter === ch.id;
            const isRevising = revisingChapter === ch.id;
            const isSuggesting = suggestingChapter === ch.id;
            const isEditing = editingChapter === ch.id;
            const isSaving = savingChapter === ch.id;
            const chapterSuggestions = suggestionsChapter === ch.id ? trackingSuggestions : [];
            const review = ch.review;
            const aiScore = review?.ai_flavor_score ?? null;
            const aiSev = aiSevOf(aiScore);
            const maxSeverity = severityOf(review?.issues);
            const preview = contextPreviewChapter === ch.id ? contextPreview : null;
            const isPreviewLoading = contextPreviewLoading === ch.id;
            return (
              <article className="chapter-detail">
                <header className="chapter-head">
                  <div className="crumbs">
                    {isReference ? `参考资料 · ${vol.title}` : `第 ${vol.order_index + 1} 卷 · ${vol.title}`}
                  </div>
                  <h2>{ch.title}</h2>
                  <div className="badges">
                    {isReference && <span className="badge reference">参考资料</span>}
                    <span className={`badge ${drafted ? "drafted" : ""}`}>
                      {drafted
                        ? isReference
                          ? `原文 ${ch.word_count}字`
                          : `已成稿 ${ch.word_count}字`
                        : isReference
                        ? "暂无原文"
                        : "待写"}
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
                  <div className="chapter-outline">{isReference ? "说明" : "大纲"}：{ch.outline}</div>
                  <div className="chapter-actions">
                    {!isReference && (
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
                    )}
                    {drafted && (
                      <>
                        <button
                          className="gen"
                          disabled={isEditing || isSaving || isRevising || isReviewing || writingChapter !== ""}
                          onClick={() => startEditChapter(ch.id, ch.content || "")}
                        >
                          {isReference ? "编辑原文" : "编辑正文"}
                        </button>
                        {!isReference && (
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
                            {trackingItems.length > 0 && (
                              <button
                                className="gen secondary"
                                disabled={isSuggesting || isRevising || isReviewing || writingChapter !== ""}
                                onClick={() => suggestTracking(ch.id)}
                              >
                                {isSuggesting ? "分析线索中…" : "线索建议"}
                              </button>
                            )}
                          </>
                        )}
                        <button
                          className="gen secondary"
                          disabled={busy === "continuation-anchor" || writingChapter !== "" || continuationAnchorId === ch.id}
                          onClick={() => setContinuationAnchor(ch.id)}
                        >
                          {continuationAnchorId === ch.id ? "已是续写起点" : "设为续写起点"}
                        </button>
                      </>
                    )}
                    {!drafted && !isReference && (
                      <button
                        className="gen"
                        disabled={isEditing || isSaving || writingChapter !== ""}
                        onClick={() => startEditChapter(ch.id, ch.content || "")}
                      >
                        手写本章
                      </button>
                    )}
                    {!drafted && isReference && (
                      <button
                        className="gen"
                        disabled={isEditing || isSaving || writingChapter !== ""}
                        onClick={() => startEditChapter(ch.id, ch.content || "")}
                      >
                        补充原文
                      </button>
                    )}
                  </div>
                </header>

                {!isReference && (
                  <section className="context-preview">
                    <div className="context-preview-head">
                      <div>
                        <h3>续写上下文预览</h3>
                        <p>生成本章前，系统会优先参考这些资料来源。</p>
                      </div>
                      <button
                        className="mini secondary"
                        disabled={isPreviewLoading}
                        onClick={() => reloadContextPreview(ch.id)}
                      >
                        {isPreviewLoading ? "刷新中…" : "刷新"}
                      </button>
                    </div>
                    {isPreviewLoading && !preview && <div className="hint">正在整理上下文…</div>}
                    {preview && (
                      <>
                        <div className="context-metrics">
                          <span>角色 {preview.characters_count}</span>
                          <span>设定 {preview.world_settings_count}</span>
                          <span>线索 {preview.tracking_count}</span>
                          <span>真相 {preview.truth_files_count}</span>
                          <span>文风 {preview.has_style_fingerprint ? "已注入" : "默认"}</span>
                          <span>摘要 {preview.recent_summaries.length}</span>
                          <span>召回 {preview.recalled_chunks.length}</span>
                        </div>
                        {preview.notes.length > 0 && (
                          <div className="context-notes">
                            {preview.notes.map((note) => <span key={note}>{note}</span>)}
                          </div>
                        )}

                        <div className="context-block">
                          <strong>续写起点</strong>
                          {preview.continuation_anchor ? (
                            <>
                              <div className="meta">
                                {preview.continuation_anchor.volume_kind === "reference" ? "参考资料" : "正文"} · {preview.continuation_anchor.volume_title} / {preview.continuation_anchor.chapter_title}
                              </div>
                              {preview.continuation_anchor.summary && (
                                <div className="meta">摘要：{preview.continuation_anchor.summary}</div>
                              )}
                              {preview.continuation_anchor.entity_states.length > 0 && (
                                <div className="context-mini-list">
                                  {preview.continuation_anchor.entity_states.map((state) => <span key={state}>{state}</span>)}
                                </div>
                              )}
                              {preview.continuation_anchor.tail && (
                                <details>
                                  <summary>查看续写起点结尾</summary>
                                  <div className="context-snippet">{preview.continuation_anchor.tail}</div>
                                </details>
                              )}
                            </>
                          ) : (
                            <div className="hint">没有可注入的续写起点。</div>
                          )}
                        </div>

                        {preview.previous_tail && (
                          <div className="context-block">
                            <strong>同卷上一章结尾</strong>
                            <details>
                              <summary>查看正文尾巴</summary>
                              <div className="context-snippet">{preview.previous_tail}</div>
                            </details>
                          </div>
                        )}

                        {preview.recent_summaries.length > 0 && (
                          <div className="context-block">
                            <strong>同卷最近摘要</strong>
                            <div className="context-list">
                              {preview.recent_summaries.map((item) => (
                                <div key={item.chapter_id}>
                                  <b>{item.title}</b>
                                  <span>{item.summary}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {preview.recalled_chunks.length > 0 && (
                          <div className="context-block">
                            <strong>检索召回</strong>
                            <div className="context-list">
                              {preview.recalled_chunks.map((chunk, idx) => (
                                <div key={`${chunk.source_type}-${chunk.source_id}-${idx}`} className="context-source-card">
                                  <div className="context-source-head">
                                    <div>
                                      <b>{chunk.source_title || contextSourceLabel(chunk.source_type)}</b>
                                      <small>{chunk.source_subtitle || contextSourceLabel(chunk.source_type)} · 分数 {chunk.score}</small>
                                    </div>
                                    {chunk.target_type && (
                                      <button className="mini secondary" onClick={() => jumpToContextSource(chunk)}>
                                        跳转
                                      </button>
                                    )}
                                  </div>
                                  <span>{chunk.text}</span>
                                  <div className="context-match-row">
                                    {chunk.matched_keywords.length > 0 && <small>命中：{chunk.matched_keywords.slice(0, 6).join("、")}</small>}
                                    {chunk.keywords.length > 0 && <small>关键词：{chunk.keywords.slice(0, 6).join("、")}</small>}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {preview.entity_states.length > 0 && (
                          <div className="context-block">
                            <strong>当前角色状态</strong>
                            <div className="context-mini-list">
                              {preview.entity_states.map((item) => (
                                <span key={item.character_id}>{item.character_name}：{formatEntityState(item.state)}</span>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </section>
                )}

                {isWriting && chapterText && (
                  <div className="output stream">{chapterText}</div>
                )}

                {!isWriting && isEditing && (
                  <div className="chapter-editor">
                    <textarea
                      value={draftText}
                      onChange={(e) => setDraftText(e.target.value)}
                      placeholder={isReference ? "在这里编辑参考原文" : "在这里编辑本章正文"}
                    />
                    <div className="chapter-editor-bar">
                      <span>{draftText.length} 字</span>
                      <div className="chapter-actions">
                        <button
                          className="gen"
                          disabled={isSaving}
                          onClick={() => saveChapterContent(ch.id)}
                        >
                          {isSaving ? "保存并刷新记忆中…" : isReference ? "保存参考资料" : "保存并刷新记忆"}
                        </button>
                        <button
                          className="gen secondary"
                          disabled={isSaving}
                          onClick={cancelEditChapter}
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {!isWriting && !isEditing && drafted && (
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
                    {suggestionsChapter === ch.id && (
                      <div className="tracking-suggestions">
                        <h3>线索状态建议</h3>
                        {chapterSuggestions.length === 0 ? (
                          <div className="hint">本章没有可应用的线索状态建议。</div>
                        ) : (
                          chapterSuggestions.map((suggestion) => {
                            const canApply =
                              suggestion.suggested_status !== "no_change" &&
                              suggestion.suggested_status !== suggestion.current_status;
                            return (
                              <article key={suggestion.foreshadow_id} className="tracking-suggestion">
                                <div className="thread-card-title">
                                  <strong>{suggestion.title}</strong>
                                  <span>
                                    {statusLabel(suggestion.current_status)} → {statusLabel(suggestion.suggested_status)} · {suggestion.confidence}%
                                  </span>
                                </div>
                                {suggestion.evidence && <div className="meta">证据：{suggestion.evidence}</div>}
                                {suggestion.rationale && <div className="meta">理由：{suggestion.rationale}</div>}
                                <button
                                  className="mini secondary"
                                  disabled={!canApply || busy === "tracking-apply"}
                                  onClick={() => applyTrackingSuggestion(suggestion)}
                                >
                                  {canApply ? "应用状态" : "无需应用"}
                                </button>
                              </article>
                            );
                          })
                        )}
                      </div>
                    )}
                    {ch.content && <div className="output">{ch.content}</div>}
                  </>
                )}

                {!isWriting && !isEditing && !drafted && (
                  <div className="hint center">
                    {isReference ? "参考章节暂无原文，可编辑补充。" : "本章尚未生成，点上方「生成本章」。"}
                  </div>
                )}
              </article>
            );
          })()
        )}
      </main>
    </div>
  );
}
