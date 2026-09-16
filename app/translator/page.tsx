'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import SlidesPanel from '@/components/SlidesPanel';
import ThemeToggle from '@/components/ThemeToggle';

// --- Types ---
interface TextRun { run_id: string; text: string; style: { font_size: number | null; font_color: string | null; font_name: string | null; bold: boolean; italic: boolean; underline: boolean; }; merged_span?: [number, number] | null; }
interface TextBox { box_id: string; shape_type: string; runs: TextRun[]; constraints: { left: number; top: number; width: number; height: number; }; }
interface Slide { slide_index: number; slide_id: number; text_boxes: TextBox[]; }
interface UploadedDocument { job_id: string; filename: string; total_slides: number; total_text_boxes: number; total_runs: number; slides: Slide[]; }
interface TranslatedRun { run_id: string; original_text: string; translated_text: string; source_language: string; target_language: string; model_used: string; adjusted_font_size: number | null; }
// Served by /api/models (backend model_catalog). The page never carries its own
// copy of the list: the hardcoded one had drifted from the registry behind it.
interface CatalogModel { key: string; label: string; lane: 'gemini' | 'opencode'; model: string; note?: string; }
interface ModelCatalog { translate: CatalogModel[]; vision: CatalogModel[]; defaults: { translate: string; vision: string }; }
interface QaIssue { slide: number; type: string; severity: string; where?: string | null; detail?: string | null; }
interface QaReport {
  model?: string; slides_rendered?: number; slides_checked?: number; summary?: string;
  issues: QaIssue[]; errors?: { slide: number; error: string }[];
  /** The deck's length, so the panel knows how many chunks a full check needs. */
  deck_slides?: number | null;
  first_slide?: number | null; last_slide?: number | null;
}

// A slide check takes minutes (one vision call per slide, ~85 s each) so the backend
// runs it detached and this panel polls. Five seconds is enough to feel live without
// hammering the backend while a slow model thinks.
const QA_POLL_MS = 5000;
interface HealthStatus { settings: Record<string, boolean | string>; }
interface BatchItem {
  file: File;
  name: string;
  size: number;
  status: 'waiting' | 'processing' | 'done' | 'failed';
  error?: string;
  blobUrl?: string;
}

// --- i18n ---
type UI = 'en' | 'ja';
const en = {
  title: 'PPTX Translator',
  subtitle: 'Translate PowerPoint slides',
  desc: 'Upload a .pptx file to extract and translate text while preserving formatting.',
  uploadPrompt: 'Drag a file here or click to browse',
  uploadHint: '.pptx files up to 100MB',
  extracting: 'Extracting text from PowerPoint...',
  from: 'From', to: 'To',
  model: 'Translation model',
  context: 'Translation context (optional)',
  contextPlaceholder: 'e.g., formal business tone, technical terminology',
  glossary: 'Glossary terms (optional)',
  glossaryPlaceholder: 'List terms to keep untranslated, one per line.\ne.g., Project X, Brand Z, Azure',
  translate: 'Translate', translating: 'Translating...',
  download: 'Download PPTX', downloading: 'Exporting...',
  slides: 'slides', runs: 'text runs',
  startOver: 'Start over',
  review: 'Translations',
  done: 'done', failed: 'failed',
  original: 'Original', translation: 'Translation',
  preview: 'Preview',
  noApiKeys: 'No API keys configured', modelsReady: 'ready',
  onlyPptx: 'Only .pptx files are supported',
  uploadFailed: 'Upload failed', noText: 'No text runs found to translate',
  translationFailed: 'Translation failed', exportFailed: 'Export failed',
  slideLabel: 'Slide',
  previewSlides: 'Preview slides',
  generatingPreview: 'Generating preview images...',
  previewError: 'Could not generate preview images',
  previewOriginal: 'Before (original)', previewTranslated: 'After (translated)',
  slideCheck: 'Slide check (vision)',
  slideCheckHint: 'Reads the translated slides as images and reports layout damage — text spilling out of a box, overlap, clipping. Report-only: it never changes the deck.',
  slideCheckModel: 'Vision model',
  runSlideCheck: 'Check slides',
  checking: 'Checking…',
  slideCheckClean: 'No layout damage reported.',
  slideCheckErrored: 'Slides the check could not read:',
  slideCheckError: 'The slide check failed.',
  slideCheckOptIn: 'Opt-in — runs only when you press the button.',
  slideCheckProgress: 'Checking slides',
  slideCheckPartialLead: 'slides reviewed before it stopped:',
  slideImage: 'Slide image',
  previous: 'Previous', next: 'Next',
  renderingPreview: 'Rendering slides...',
  trySample: 'Try with a sample deck',
  sampleLoading: 'Loading sample…',
  sampleError: 'Could not load the sample deck',
  batchTranslateAll: 'Translate all',
  batchProcessing: 'Processing {i}/{n}: {name}',
  batchDone: 'Done', batchFailed: 'Failed',
  downloadAll: 'Download all',
};
const ja: typeof en = {
  title: 'PPTX翻訳',
  subtitle: 'PowerPointスライドを翻訳',
  desc: 'pptxファイルをアップロードして、テキストを抽出・翻訳。フォーマットはそのまま保持します。',
  uploadPrompt: 'ファイルをドラッグ＆ドロップ、またはクリックして選択',
  uploadHint: '.pptx ファイル（100MBまで）',
  extracting: 'PowerPointからテキストを抽出中...',
  from: '翻訳元', to: '翻訳先',
  model: '翻訳モデル',
  context: '翻訳コンテキスト（任意）',
  contextPlaceholder: '例：フォーマルなビジネス文書、技術用語を多用',
  glossary: '訳さない用語（任意）',
  glossaryPlaceholder: '原文のまま残す用語を1行ずつ入力\n例：Project X、Azure',
  translate: '翻訳する', translating: '翻訳中...',
  download: 'PPTXをダウンロード', downloading: 'エクスポート中...',
  slides: 'スライド', runs: 'テキスト',
  startOver: '最初から',
  review: '翻訳結果',
  done: '完了', failed: '失敗',
  original: '原文', translation: '翻訳文',
  preview: 'プレビュー',
  noApiKeys: 'APIキーが設定されていません', modelsReady: '利用可能',
  onlyPptx: '.pptxファイルのみ対応しています',
  uploadFailed: 'アップロード失敗', noText: '翻訳するテキストが見つかりません',
  translationFailed: '翻訳失敗', exportFailed: 'エクスポート失敗',
  slideLabel: 'スライド',
  previewSlides: 'スライドプレビュー',
  generatingPreview: 'プレビュー画像を生成中...',
  previewError: 'プレビュー画像を生成できませんでした',
  previewOriginal: 'ビフォー（原文）', previewTranslated: 'アフター（翻訳後）',
  slideCheck: 'スライド検査（画像）',
  slideCheckHint: '翻訳後のスライドを画像として読み、レイアウトの崩れ（テキストのはみ出し・重なり・欠け）を報告します。報告のみで、資料は変更しません。',
  slideCheckModel: '画像モデル',
  runSlideCheck: '検査する',
  checking: '検査中…',
  slideCheckClean: 'レイアウトの崩れは報告されませんでした。',
  slideCheckErrored: '読み取れなかったスライド:',
  slideCheckError: 'スライド検査に失敗しました。',
  slideCheckOptIn: '任意実行 — ボタンを押したときだけ実行されます。',
  slideCheckProgress: '検査中',
  slideCheckPartialLead: '中断までに検査できたスライド:',
  slideImage: 'スライド画像',
  previous: '前へ', next: '次へ',
  renderingPreview: 'スライドをレンダリング中...',
  trySample: 'サンプルファイルで試す',
  sampleLoading: 'サンプル読み込み中…',
  sampleError: 'サンプルファイルを読み込めませんでした',
  batchTranslateAll: 'すべて翻訳',
  batchProcessing: '処理中 {i}/{n}: {name}',
  batchDone: '完了', batchFailed: '失敗',
  downloadAll: 'すべてダウンロード',
};
const t = (ui: UI) => ui === 'en' ? en : ja;

/** Poll a job until it leaves "processing". Returns the final status, or null on timeout. */
async function waitForJob(jobId: string, timeoutMs = 60 * 60 * 1000): Promise<string | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.status && data.status !== 'processing' && data.status !== 'pending') return data.status as string;
      }
    } catch { /* transient — keep waiting */ }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  return null;
}

export default function NewTranslatorPage() {
  const [ui, setUi] = useState<UI>('en');
  const [mode, setMode] = useState<'pptx' | 'slides'>('pptx');
  const text = t(ui);

  const [document, setDocument] = useState<UploadedDocument | null>(null);
  const [translatedRuns, setTranslatedRuns] = useState<TranslatedRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [sourceLang, setSourceLang] = useState<'ja' | 'en'>('en');
  const [targetLang, setTargetLang] = useState<'ja' | 'en'>('ja');
  const [model, setModel] = useState<string>('gemini-25-flash-lite');
  // The catalog decides what the pickers offer, so a list edit in the backend shows
  // up here without touching this file.
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [visionModel, setVisionModel] = useState<string>('');
  const [qaReport, setQaReport] = useState<QaReport | null>(null);
  const [qaRunning, setQaRunning] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);
  const [qaProgress, setQaProgress] = useState<{ checked: number; total: number | null } | null>(null);
  // Bumped per run so a superseded loop stops instead of writing a stale report.
  const qaRunRef = useRef(0);
  const [contextPrompt, setContextPrompt] = useState('');
  const [glossaryTerms, setGlossaryTerms] = useState(''); // New state for glossary
  const [sampleLoading, setSampleLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Preview state
  const [previewImages, setPreviewImages] = useState<string[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewWhich, setPreviewWhich] = useState<'translated' | 'original'>('translated');
  const [currentSlide, setCurrentSlide] = useState(0);

  // Live progress polling (translate phase)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [runProgress, setRunProgress] = useState<{ done: number; total: number } | null>(null);

  // Batch mode state
  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchCurrent, setBatchCurrent] = useState(0);

  const runBatch = useCallback(async (items: BatchItem[]) => {
    setBatchRunning(true);
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      setBatchCurrent(i);
      setBatchItems(prev => prev.map((b, bi) => bi === i ? { ...b, status: 'processing' as const } : b));
      try {
        // Upload
        const fd = new FormData();
        fd.append('file', item.file);
        const upRes = await fetch('/api/upload-new', { method: 'POST', body: fd });
        if (!upRes.ok) throw new Error(text.uploadFailed);
        const doc: UploadedDocument = await upRes.json();

        // Translate
        const allRuns: TextRun[] = [];
        for (const slide of doc.slides) for (const tb of slide.text_boxes) allRuns.push(...tb.runs);
        if (allRuns.length > 0) {
          const body: Record<string, unknown> = { runs: allRuns, source_language: sourceLang, target_language: targetLang, model, job_id: doc.job_id };
          if (contextPrompt.trim()) body.context = contextPrompt.trim();
          if (glossaryTerms.trim()) body.glossary = glossaryTerms.split('\n').map(s => s.trim()).filter(Boolean);
          const trRes = await fetch('/api/translate-new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          if (!trRes.ok) throw new Error(text.translationFailed);
          // The backend queues the translation and answers at once, so wait for the
          // job to actually finish — exporting now would write a half-translated deck.
          const jobStatus = await waitForJob(doc.job_id);
          if (jobStatus !== 'completed') throw new Error(text.translationFailed);
        }

        // Export to blob URL for later download
        const exRes = await fetch('/api/export-new', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id: doc.job_id, filename: `translated_${doc.filename}` }),
        });
        if (!exRes.ok) throw new Error(text.exportFailed);
        const blob = await exRes.blob();
        const url = URL.createObjectURL(blob);
        setBatchItems(prev => prev.map((b, bi) => bi === i ? { ...b, status: 'done' as const, blobUrl: url } : b));
      } catch (err) {
        setBatchItems(prev => prev.map((b, bi) => bi === i ? { ...b, status: 'failed' as const, error: err instanceof Error ? err.message : 'error' } : b));
      }
    }
    setBatchRunning(false);
  }, [sourceLang, targetLang, model, contextPrompt, glossaryTerms, text]); // eslint-disable-line react-hooks/exhaustive-deps

  const addBatchFiles = useCallback((files: FileList | null) => {
    if (!files) return;
    const valid: BatchItem[] = Array.from(files)
      .filter(f => f.name.endsWith('.pptx'))
      .map(f => ({ file: f, name: f.name, size: f.size, status: 'waiting' as const }));
    if (valid.length > 0) setBatchItems(prev => [...prev, ...valid]);
  }, []);

  const [restoreJobId, setRestoreJobId] = useState<string | null>(null);

  // Restore handler
  const handleRestore = useCallback(async (jobId: string) => {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/jobs/${jobId}?full=1`);
      if (!res.ok) throw new Error('Failed to load previous session');
      const data = await res.json();
      // Restore rebuilds the whole editor from this response, and the status
      // poll's trimmed shape has no slides: setting it as the document produced
      // "undefined · undefined slides" and translating it threw
      // "x.slides is not iterable". Refuse a document we cannot translate.
      if (!Array.isArray(data.slides)) throw new Error('Failed to load previous session');
      setDocument(data);
      setTranslatedRuns(data.translated_runs || []);
      setProgress(data.progress || 0);
      // Don't auto-generate preview on restore for performance.
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load previous session');
      try { localStorage.removeItem('jpeigo-last-job-id'); } catch(e){/*no-op*/}
      setRestoreJobId(null);
    } finally {
      setLoading(false);
    }
  }, [ui]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // Check for a job ID in localStorage on initial load
    try {
      const storedJobId = localStorage.getItem('jpeigo-last-job-id');
      if (storedJobId) {
        setRestoreJobId(storedJobId);
      }
    } catch (e) {
      // localStorage unavailable (private mode)
    }

    fetch('/api/health')
      .then(r => r.json())
      .then(data => setHealth(data))
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    fetch('/api/health')
      .then(r => r.json())
      .then(data => setHealth(data))
      .catch(() => setHealth(null));
  }, []);

  const configuredModels = health?.settings
    ? Object.entries(health.settings).filter(([k, v]) => k.endsWith('_configured') && v === true).map(([k]) => k.replace('_configured', ''))
    : [];

  // Generate preview images after translation
  // which: 'translated' is the exported deck, 'original' the file as uploaded — the
  // two sides together are the before/after view. Switching back to a side already
  // rendered is instant because the preview route caches each side separately.
  const generatePreview = useCallback(async (jobId: string, filename: string, which: 'translated' | 'original' = 'translated') => {
    setPreviewWhich(which);
    setPreviewLoading(true);
    setPreviewError(null);
    setCurrentSlide(0);
    try {
      const res = await fetch('/api/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, filename, which }),
      });
      if (!res.ok) throw new Error(text.previewError);
      const data = await res.json();
      setPreviewImages(data.images || []);
    } catch {
      setPreviewError(text.previewError);
    } finally {
      setPreviewLoading(false);
    }
  }, [ui]); // eslint-disable-line react-hooks/exhaustive-deps

  // Which models may be offered comes from the backend, so the picker and the
  // translation registry cannot disagree about a label.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/models')
      .then(res => (res.ok ? res.json() : Promise.reject(new Error('catalog'))))
      .then((data: ModelCatalog) => {
        if (cancelled) return;
        setCatalog(data);
        setVisionModel(prev => prev || data.defaults.vision);
        setModel(prev => (data.translate.some(m => m.key === prev) ? prev : data.defaults.translate));
      })
      .catch(() => { /* the picker falls back to whatever the registry default is */ });
    return () => { cancelled = true; };
  }, []);

  // The slide check is opt-in and report-only: it renders the slides and asks a
  // vision model what looks broken. It never edits the deck and never blocks export.
  // The backend runs the check detached (minutes, one vision call per slide) and this
  // only starts it and polls, so a slow-but-accurate model never costs us the run.
  const runSlideCheck = useCallback(async (jobId: string) => {
    const run = qaRunRef.current + 1;
    qaRunRef.current = run;
    setQaRunning(true); setQaError(null); setQaReport(null); setQaProgress(null);
    let checked = 0, rendered = 0;
    try {
      const started = await fetch('/api/qa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, which: 'translated', model: visionModel }),
      });
      const start = await started.json().catch(() => null);
      if (!started.ok) throw new Error(start?.error || start?.detail || text.slideCheckError);

      for (;;) {
        await new Promise(resolve => setTimeout(resolve, QA_POLL_MS));
        if (qaRunRef.current !== run) return;
        const status = await fetch(
          `/api/qa?job_id=${encodeURIComponent(jobId)}&which=translated`,
          { cache: 'no-store' },
        );
        const state = await status.json().catch(() => null);
        if (!status.ok) throw new Error(state?.error || state?.detail || text.slideCheckError);
        if (qaRunRef.current !== run) return;

        // Publish whatever the backend already reviewed: findings show up slide by
        // slide, and a poll that fails never discards the slides done so far.
        if (state?.report) setQaReport(state.report);
        checked = state?.report?.slides_checked ?? state?.checked ?? checked;
        rendered = state?.report?.slides_rendered ?? rendered;
        setQaProgress({ checked, total: state?.total ?? null });

        if (state?.state === 'done') break;
        if (state?.state === 'failed') throw new Error(state?.error || text.slideCheckError);
      }
    } catch (e) {
      const reason = e instanceof Error && e.message ? e.message : text.slideCheckError;
      // Say how far the check got: an interrupted run leaves slides unread, and
      // "failed" alone would read as "nothing was reviewed".
      if (qaRunRef.current === run) {
        setQaError(checked ? `${reason} — ${text.slideCheckPartialLead} ${checked}/${rendered}` : reason);
      }
    } finally {
      if (qaRunRef.current === run) { setQaRunning(false); setQaProgress(null); }
    }
  }, [visionModel, ui]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleFile = useCallback(async (file: File) => {
    if (!file.name.endsWith('.pptx')) { setError(text.onlyPptx); return; }
    setLoading(true); setError(null); setProgress(0); setTranslatedRuns([]);
    setPreviewImages([]); setPreviewError(null);
    try {
      const formData = new FormData(); formData.append('file', file);
      const response = await fetch('/api/upload-new', { method: 'POST', body: formData });
      if (!response.ok) { const err = await response.json().catch(() => ({ error: text.uploadFailed })); throw new Error(err.error || text.uploadFailed); }
      const data = await response.json(); setDocument(data); setProgress(100);
      try {
        localStorage.setItem('jpeigo-last-job-id', data.job_id);
      } catch (e) { /* no-op if localStorage is unavailable */ }
    } catch (err) { setError(err instanceof Error ? err.message : text.uploadFailed); }
    finally { setLoading(false); }
  }, [ui]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDrop = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragOver(false); const file = e.dataTransfer.files?.[0]; if (file) handleFile(file); }, [handleFile]);

  const handleTranslate = useCallback(async () => {
    if (!document) return;
    setTranslating(true); setError(null); setApiError(null); setProgress(0);
    setPreviewImages([]); setPreviewError(null);
    setRunProgress(null);

    const stopPolling = () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };

    // The backend queues the translation and answers immediately, so this poll is
    // what reports progress and the only place a failure ever surfaces: a job that
    // dies carries status "failed" plus the error, and would otherwise be waited on
    // forever.
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`/api/jobs/${document.job_id}`);
        if (!r.ok) return;
        const d = await r.json();
        const pct = Math.round(d.progress || 0);
        setProgress(pct);
        if (d.status === 'failed') {
          stopPolling();
          setRunProgress(null);
          setTranslating(false);
          setError(d.error ? `${text.translationFailed} (${d.error})` : text.translationFailed);
          return;
        }
        if (d.status === 'completed') {
          // The status endpoint deliberately carries no runs — the 2s poll has to
          // stay cheap — so read the full record once, the same call Restore uses.
          // Assigning runs unconditionally from the light payload is what blanked a
          // finished translation right after it appeared.
          let runs: TranslatedRun[] = [];
          try {
            const full = await fetch(`/api/jobs/${document.job_id}?full=1`);
            if (full.ok) runs = (await full.json()).translated_runs || [];
          } catch { /* keep whatever is already on screen */ }
          if (runs.length > 0) {
            setTranslatedRuns(runs);
            const failed = runs.filter(x => x.original_text === x.translated_text && x.model_used !== 'cache');
            setApiError(failed.length > 0 ? `${failed.length} of ${runs.length} runs couldn't be translated.` : null);
          }
          stopPolling();
          setProgress(100);
          setRunProgress(null);
          setTranslating(false);
          setError(null);
          generatePreview(document.job_id, document.filename);
          return;
        }
        if (d.total_runs) setRunProgress({ done: Math.round((pct / 100) * d.total_runs), total: d.total_runs });
      } catch { /* transient — next tick retries */ }
    }, 2000);

    try {
      const allRuns: TextRun[] = [];
      for (const slide of document.slides) for (const textBox of slide.text_boxes) allRuns.push(...textBox.runs);
      if (allRuns.length === 0) throw new Error(text.noText);
      const body: Record<string, unknown> = { runs: allRuns, source_language: sourceLang, target_language: targetLang, model, job_id: document.job_id };
      if (contextPrompt.trim()) body.context = contextPrompt.trim();
      if (glossaryTerms.trim()) body.glossary = glossaryTerms.split('\n').map(s => s.trim()).filter(Boolean);
      const response = await fetch('/api/translate-new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) { const err = await response.json().catch(() => ({ error: text.translationFailed })); throw new Error(err.error || text.translationFailed); }
      const data = await response.json();
      // The reply only acknowledges the queue ("processing"); the runs arrive through
      // the poll above. A duplicate click can be answered with the state of the run
      // already in flight, which may be finished or failed by then.
      if (data.status === 'failed') throw new Error(data.error || text.translationFailed);
      if (data.status === 'completed' && Array.isArray(data.translated_runs) && data.translated_runs.length > 0) {
        setTranslatedRuns(data.translated_runs);
        const failed = data.translated_runs.filter((r: TranslatedRun) => r.original_text === r.translated_text && r.model_used !== 'cache');
        setApiError(failed.length > 0 ? `${failed.length} of ${data.translated_runs.length} runs couldn't be translated.` : null);
        stopPolling();
        setProgress(100);
        setRunProgress(null);
        setTranslating(false);
        generatePreview(document.job_id, document.filename);
      }
      // Otherwise the job is still running — the poll clears the state when it lands.
    } catch (err) {
      console.error('Frontend Translation Error:', err);
      stopPolling();
      setRunProgress(null);
      setTranslating(false);
      // No error clearing here — errors are cleared at the start of the run. Clearing
      // them in a finally wiped the failure message, and the partial-failure warning
      // set just below, the instant they were set, so neither was ever visible.
      setError(err instanceof Error ? (err.message || String(err)) : text.translationFailed);
    }
  }, [document, sourceLang, targetLang, model, contextPrompt, glossaryTerms, ui]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleExport = useCallback(async () => {
    if (!document || translatedRuns.length === 0) return;
    setExporting(true); setError(null);
    try {
      const response = await fetch('/api/export-new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: document.job_id, filename: `translated_${document.filename}` }) });
      if (!response.ok) { const err = await response.json().catch(() => ({ error: text.exportFailed })); throw new Error(err.error || text.exportFailed); }
      // The export body is the PPTX, so injection failures arrive as headers.
      const injectionFailures = Number(response.headers.get('X-Injection-Failed') || 0);
      const injectionTotal = Number(response.headers.get('X-Injection-Total') || 0);
      setApiError(injectionFailures > 0 ? `${injectionFailures} of ${injectionTotal} text runs could not be placed in the exported deck.` : null);
      const blob = await response.blob(); const url = window.URL.createObjectURL(blob);
      const a = window.document.createElement('a'); a.href = url; a.download = `translated_${document.filename}`;
      window.document.body.appendChild(a); a.click(); window.document.body.removeChild(a); window.URL.revokeObjectURL(url);
    } catch (err) { setError(err instanceof Error ? err.message : text.exportFailed); }
    finally { setExporting(false); }
  }, [document, translatedRuns, ui]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleTextEdit = useCallback((runId: string, newText: string) => { setTranslatedRuns(prev => prev.map(r => r.run_id === runId ? { ...r, translated_text: newText } : r)); }, []);

  const resetAll = useCallback(() => {
    setDocument(null); setTranslatedRuns([]); setError(null); setApiError(null);
    setProgress(0); setPreviewImages([]); setPreviewError(null); setCurrentSlide(0);
    try { localStorage.removeItem('jpeigo-last-job-id'); } catch (e) { /* no-op */ }
  }, []);

  const completedCount = translatedRuns.filter(r => r.original_text !== r.translated_text || r.model_used === 'cache').length;
  const failedCount = translatedRuns.filter(r => r.original_text === r.translated_text && r.model_used !== 'cache').length;
  const allDone = document && translatedRuns.length > 0 && !translating;

  const fileInfo = document ? `${document.filename}  ·  ${document.total_slides} ${text.slides}, ${document.total_runs} ${text.runs}` : '';

  // Helper: get translated runs for a specific slide
  const getSlideTextEntries = (slideIdx: number) => {
    if (!document) return [];
    const slide = document.slides[slideIdx];
    if (!slide) return [];
    const entries: { run: TextRun; tr?: TranslatedRun; isFailed: boolean; boxId: string }[] = [];
    slide.text_boxes.forEach(tb =>
      tb.runs.forEach(run => {
        const tr = translatedRuns.find(t => t.run_id === run.run_id);
        const isFailed = !!tr && tr.original_text === tr.translated_text && tr.model_used !== 'cache';
        entries.push({ run, tr, isFailed, boxId: tb.box_id });
      })
    );
    return entries;
  };

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 flex flex-col">
      {/* --- Header --- */}
      <header className="bg-white dark:bg-zinc-950 border-b border-gray-200 dark:border-zinc-800">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <svg width="20" height="20" viewBox="0 0 24 24" className="fill-zinc-500 dark:fill-zinc-400">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
            </svg>
            <span className="text-sm font-medium text-gray-700 dark:text-zinc-200 select-none">{text.title}</span>
          </div>
          <div className="flex items-center gap-4 text-sm">
            {/* Mode Toggle: PPTX vs Google Slides */}
            <div className="flex items-center bg-gray-100 dark:bg-zinc-800 rounded-lg p-0.5">
              <button onClick={() => { setMode('pptx'); resetAll(); }} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${mode === 'pptx' ? 'bg-white dark:bg-zinc-700 text-gray-700 dark:text-zinc-100 shadow-sm' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-700 dark:hover:text-zinc-200'}`}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" className="inline-block mr-1 -mt-0.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                PPTX
              </button>
              <button onClick={() => { setMode('slides'); resetAll(); }} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${mode === 'slides' ? 'bg-white dark:bg-zinc-700 text-gray-700 dark:text-zinc-100 shadow-sm' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-700 dark:hover:text-zinc-200'}`}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" className="inline-block mr-1 -mt-0.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
                Slides
              </button>
            </div>
            {/* EN/JP Toggle */}
            <div className="flex items-center bg-gray-100 dark:bg-zinc-800 rounded-lg p-0.5">
              <button onClick={() => setUi('en')} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${ui === 'en' ? 'bg-white dark:bg-zinc-700 text-gray-700 dark:text-zinc-100 shadow-sm' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-700 dark:hover:text-zinc-200'}`}>EN</button>
              <button onClick={() => setUi('ja')} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${ui === 'ja' ? 'bg-white dark:bg-zinc-700 text-gray-700 dark:text-zinc-100 shadow-sm' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-700 dark:hover:text-zinc-200'}`}>JP</button>
            </div>
            <ThemeToggle />
            {health && (
              <span className="flex items-center gap-1.5 text-gray-500 dark:text-zinc-400">
                <span className={`w-2 h-2 rounded-full ${configuredModels.length > 0 ? 'bg-green-500' : 'bg-yellow-500'}`} />
                <span className="text-xs">{configuredModels.length > 0 ? `${configuredModels.length} ${text.modelsReady}` : text.noApiKeys}</span>
              </span>
            )}
            {document && (
              <button onClick={resetAll} className="text-blue-600 hover:text-blue-700 hover:underline text-xs">{text.startOver}</button>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">
        <div className="max-w-5xl mx-auto px-6 py-12">

          {/* Error */}
          {error && (
            <div className="mb-6 px-4 py-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-lg text-sm text-red-700 dark:text-red-300">{error}</div>
          )}

          {/* === Upload State (PPTX mode) === */}
          {mode === 'pptx' && !document && !loading && !error && (
            <div className="max-w-xl mx-auto mt-12">
              <div className="text-center mb-8">
                {restoreJobId && !loading && !document && (
                  <div className="mb-6 px-4 py-3 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900 rounded-lg text-sm text-blue-700 dark:text-blue-300">
                    Found previous session: <button onClick={() => handleRestore(restoreJobId)} className="font-medium underline">Restore</button>
                    <button onClick={() => { try { localStorage.removeItem('jpeigo-last-job-id'); } catch(e){/*no-op*/} setRestoreJobId(null); }} className="ml-3 text-blue-600 hover:text-blue-700 hover:underline">Dismiss</button>
                  </div>
                )}
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-50 dark:bg-blue-950/50 mb-4">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1a73e8" strokeWidth="1.5">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="12" y1="18" x2="12" y2="12" />
                    <line x1="9" y1="15" x2="15" y2="15" />
                  </svg>
                </div>
                <h1 className="text-2xl font-normal text-gray-800 dark:text-zinc-100 mb-2">{text.subtitle}</h1>
                <p className="text-sm text-gray-500 dark:text-zinc-400">{text.desc}</p>
              </div>
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-xl py-16 px-8 text-center cursor-pointer transition-all ${
                  dragOver ? 'border-blue-500 bg-blue-50 dark:bg-blue-950/40' : 'border-gray-300 dark:border-zinc-700 hover:border-gray-400 dark:hover:border-zinc-500 bg-gray-50/30 dark:bg-zinc-900/50 hover:bg-gray-50 dark:hover:bg-zinc-900'
                }`}
              >
                {/* multiple: enables multi-select; single files take the normal path via onChange */}
                <input ref={fileInputRef} type="file" accept=".pptx" multiple className="hidden" onChange={e => {
                  const files = e.target.files;
                  if (files && files.length === 1) handleFile(files[0]);
                  else if (files) addBatchFiles(files);
                  e.target.value = '';
                }} />
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#9aa0a6" strokeWidth="1.5" className="mx-auto mb-3">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                <p className="text-sm font-medium text-gray-700 dark:text-zinc-200 mb-0.5">{text.uploadPrompt}</p>
                <p className="text-xs text-gray-400 dark:text-zinc-500 mb-4">{text.uploadHint}</p>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setSampleLoading(true);
                    fetch('/sample-deck.pptx')
                      .then(r => { if (!r.ok) throw new Error(); return r.blob(); })
                      .then(b => handleFile(new File([b], 'sample-deck.pptx', { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })))
                      .catch(() => setError(text.sampleError))
                      .finally(() => setSampleLoading(false));
                  }}
                  disabled={sampleLoading}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-900 hover:bg-blue-50 dark:hover:bg-blue-950/50 disabled:opacity-50 transition-colors"
                >
                  {sampleLoading ? text.sampleLoading : text.trySample}
                </button>
              </div>

              {/* Batch mode */}
              {batchItems.length > 0 && (
                <div className="mt-6 bg-gray-50/50 dark:bg-zinc-900/60 border border-gray-200 dark:border-zinc-800 rounded-xl p-5">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-medium text-gray-500 dark:text-zinc-400 uppercase tracking-wider">
                      {batchRunning
                        ? text.batchProcessing.replace('{i}', String(batchCurrent + 1)).replace('{n}', String(batchItems.length)).replace('{name}', batchItems[batchCurrent]?.name || '')
                        : `${batchItems.filter(b => b.status === 'done').length}/${batchItems.length} ${text.done}`}
                    </h3>
                    {!batchRunning && (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => runBatch([...batchItems])}
                          disabled={batchItems.every(b => b.status !== 'waiting')}
                          className="px-4 py-1.5 rounded-lg text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 dark:disabled:bg-zinc-700 transition-colors shadow-sm"
                        >
                          {text.batchTranslateAll}
                        </button>
                        <button onClick={() => setBatchItems([])} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
                      </div>
                    )}
                  </div>
                  <ul className="space-y-2">
                    {batchItems.map((item, i) => (
                      <li key={`${item.name}-${i}`} className="flex items-center justify-between gap-3 text-sm">
                        <span className="truncate flex-1 text-gray-700 dark:text-zinc-200">{item.name}</span>
                        {item.status === 'done' && item.blobUrl && (
                          <a href={item.blobUrl} download={`translated_${item.name}`}
                            className="px-3 py-1 rounded-md text-xs font-medium bg-green-600 hover:bg-green-700 text-white transition-colors shadow-sm">
                            ⬇ {text.download}
                          </a>
                        )}
                        {item.status === 'failed' && (
                          <span className="text-xs text-red-600 dark:text-red-400">{text.failed}{item.error ? `: ${item.error}` : ''}</span>
                        )}
                        {(item.status === 'processing') && (
                          <svg className="animate-spin h-4 w-4 text-blue-500" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                        )}
                        {item.status === 'waiting' && (
                          <span className="text-xs text-gray-400 dark:text-zinc-500">…</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* === Google Slides Mode === */}
          {mode === 'slides' && !document && !loading && (
            <SlidesPanel
              ui={ui}
              sourceLang={sourceLang}
              targetLang={targetLang}
              model={model}
              contextPrompt={contextPrompt}
            />
          )}

          {/* === Upload Progress === */}
          {loading && (
            <div className="max-w-xl mx-auto mt-12">
              <div className="bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-6">
                <div className="flex items-center justify-between mb-3 text-sm">
                  <span className="text-gray-600 dark:text-zinc-300">{text.extracting}</span>
                  <span className="text-blue-600 font-medium">{progress}%</span>
                </div>
                <div className="h-2.5 bg-gray-100 dark:bg-zinc-800 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 rounded-full transition-all duration-500 ease-out" style={{ width: `${progress}%` }} />
                </div>
              </div>
            </div>
          )}

          {/* === Translate / Review State === */}
          {document && !loading && (
            <>
              {/* File info bar */}
              <div className="flex items-center gap-2.5 mb-8 pb-5 border-b border-gray-200 dark:border-zinc-800">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="stroke-zinc-500 dark:stroke-zinc-400" strokeWidth="1.5">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                <span className="text-sm text-gray-700 dark:text-zinc-200 truncate">{fileInfo}</span>
              </div>

              {/* Two column: Settings */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                {/* Languages */}
                <div className="bg-gray-50/50 dark:bg-zinc-900/60 border border-gray-200 dark:border-zinc-800 rounded-xl p-5">
                  <h3 className="text-xs font-medium text-gray-500 dark:text-zinc-400 uppercase tracking-wider mb-4">{ui === 'en' ? 'Languages' : '言語設定'}</h3>
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <label className="block text-xs text-gray-500 dark:text-zinc-400 mb-1">{text.from}</label>
                      <select value={sourceLang} onChange={e => setSourceLang(e.target.value as 'ja' | 'en')}
                        className="w-full border border-gray-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 appearance-none cursor-pointer">
                        <option value="en">English</option>
                        <option value="ja">Japanese</option>
                      </select>
                    </div>
                    <div className="pt-5">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9aa0a6" strokeWidth="1.5">
                        <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
                      </svg>
                    </div>
                    <div className="flex-1">
                      <label className="block text-xs text-gray-500 dark:text-zinc-400 mb-1">{text.to}</label>
                      <select value={targetLang} onChange={e => setTargetLang(e.target.value as 'ja' | 'en')}
                        className="w-full border border-gray-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 appearance-none cursor-pointer">
                        <option value="ja">Japanese</option>
                        <option value="en">English</option>
                      </select>
                    </div>
                  </div>
                </div>
                <div className="bg-gray-50/50 dark:bg-zinc-900/60 border border-gray-200 dark:border-zinc-800 rounded-xl p-5">
                  <h3 className="text-xs font-medium text-gray-500 dark:text-zinc-400 uppercase tracking-wider mb-4">{text.model}</h3>
                  <select value={model} onChange={e => setModel(e.target.value)}
                    className="w-full border border-gray-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 appearance-none cursor-pointer mb-3">
                    {catalog ? (
                      <>
                        {(['gemini', 'opencode'] as const).map(lane => (
                          <optgroup key={lane} label={lane === 'gemini' ? 'Google Gemini' : 'OpenCode'}>
                            {catalog.translate.filter(m => m.lane === lane).map(m => (
                              <option key={m.key} value={m.key}>
                                {m.key === catalog.defaults.translate ? '★ ' : ''}{m.label}
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </>
                    ) : (
                      // Until the catalog loads, offer the one key the backend is known
                      // to resolve rather than an empty picker.
                      <option value={model}>{model}</option>
                    )}
                  </select>
                  <input type="text" value={contextPrompt} onChange={e => setContextPrompt(e.target.value)}
                    placeholder={text.contextPlaceholder}
                    className="w-full border border-gray-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 placeholder:text-gray-400 dark:placeholder:text-zinc-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500" />
                  <label className="block text-xs text-gray-500 dark:text-zinc-400 mt-4 mb-1">{text.glossary}</label>
                  <textarea value={glossaryTerms} onChange={e => setGlossaryTerms(e.target.value)}
                    placeholder={text.glossaryPlaceholder}
                    rows={3}
                    className="w-full border border-gray-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 placeholder:text-gray-400 dark:placeholder:text-zinc-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-y" />
                </div>
              </div>

              {apiError && (
                <div className="mb-4 px-4 py-2.5 bg-yellow-50 dark:bg-yellow-950/40 border border-yellow-200 dark:border-yellow-900 rounded-lg text-sm text-yellow-700 dark:text-yellow-300">{apiError}</div>
              )}

              {/* Translate button + progress */}
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <button onClick={handleTranslate} disabled={translating}
                    className="px-6 py-2.5 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 dark:disabled:bg-zinc-700 disabled:text-gray-500 dark:disabled:text-zinc-500 transition-colors shadow-sm">
                    {translating ? text.translating : text.translate}
                  </button>
                  {allDone && (
                    <button onClick={handleExport} disabled={exporting}
                      className="px-6 py-2.5 rounded-lg text-sm font-medium text-white bg-green-600 hover:bg-green-700 disabled:bg-gray-300 dark:disabled:bg-zinc-700 transition-colors shadow-sm">
                      {exporting ? text.downloading : text.download}
                    </button>
                  )}
                  <button onClick={resetAll}
                    className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-600 dark:text-zinc-300 hover:text-gray-800 dark:hover:text-zinc-100 border border-gray-300 dark:border-zinc-700 hover:border-gray-400 dark:hover:border-zinc-500 transition-colors">
                    {text.startOver}
                  </button>
                </div>
                {allDone && translatedRuns.length > 0 && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-950/50 px-2.5 py-1 rounded-full">{completedCount}/{translatedRuns.length} {text.done}</span>
                    {failedCount > 0 && <span className="text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950/50 px-2.5 py-1 rounded-full">{failedCount} {text.failed}</span>}
                  </div>
                )}
              </div>

              {translating && (
                <div className="mb-6">
                  <div className="flex items-center justify-between text-sm mb-2">
                    <span className="text-gray-500 dark:text-zinc-400">{text.translating}</span>
                    <span className="text-blue-600 dark:text-blue-400 font-medium tabular-nums">
                      {progress}%{runProgress ? ` · ${runProgress.done}/${runProgress.total} ${text.runs}` : ''}
                    </span>
                  </div>
                  <div className="h-2 bg-gray-100 dark:bg-zinc-800 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full transition-all duration-500 ease-out" style={{ width: `${progress}%` }} />
                  </div>
                </div>
              )}

              {/* === Preview Images === */}
              {allDone && (
                <div className="mt-8 border-t border-gray-200 dark:border-zinc-800 pt-8">
                  <div className="flex items-center justify-between gap-3 mb-4">
                    <h2 className="text-base font-medium text-gray-700 dark:text-zinc-200">{text.previewSlides}</h2>
                    {document && (
                      <div className="flex rounded-lg border border-gray-200 dark:border-zinc-800 overflow-hidden text-xs">
                        {([['original', text.previewOriginal], ['translated', text.previewTranslated]] as const).map(([kind, label]) => (
                          <button
                            key={kind}
                            onClick={() => generatePreview(document.job_id, document.filename, kind)}
                            disabled={previewLoading}
                            className={`px-3 py-1.5 transition-colors disabled:opacity-50 ${previewWhich === kind ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800'}`}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Loading preview */}
                  {previewLoading && (
                    <div className="bg-gray-50 dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl p-8 text-center">
                      <svg className="animate-spin h-6 w-6 text-blue-500 mx-auto mb-3" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <p className="text-sm text-gray-500 dark:text-zinc-400">{text.generatingPreview}</p>
                      <p className="text-xs text-gray-400 dark:text-zinc-500 mt-1">{text.renderingPreview}</p>
                    </div>
                  )}

                  {/* Preview error */}
                  {previewError && !previewLoading && (
                    <div className="px-4 py-3 bg-yellow-50 dark:bg-yellow-950/40 border border-yellow-200 dark:border-yellow-900 rounded-lg text-sm text-yellow-700 dark:text-yellow-300">{previewError}</div>
                  )}

                  {/* Image viewer */}
                  {previewImages.length > 0 && !previewLoading && (
                    <div>
                      {/* Slide selector dots */}
                      <div className="flex items-center justify-center gap-2 mb-4">
                        {previewImages.map((_, i) => (
                          <button key={i} onClick={() => setCurrentSlide(i)}
                            className={`w-2 h-2 rounded-full transition-colors ${i === currentSlide ? 'bg-blue-600' : 'bg-gray-300 dark:bg-zinc-700 hover:bg-gray-400 dark:hover:bg-zinc-600'}`}
                            aria-label={`${text.slideLabel} ${i + 1}`} />
                        ))}
                      </div>

                      {/* Current slide image */}
                      <div className="bg-gray-50 dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                        <div className="bg-gray-100 dark:bg-zinc-800/60 px-4 py-2 border-b border-gray-200 dark:border-zinc-800 flex items-center justify-between">
                          <button onClick={() => setCurrentSlide(p => Math.max(0, p - 1))} disabled={currentSlide === 0}
                            className="px-3 py-1 rounded text-sm text-gray-600 dark:text-zinc-300 hover:bg-gray-200 dark:hover:bg-zinc-700 disabled:text-gray-300 dark:disabled:text-zinc-600 disabled:hover:bg-transparent dark:disabled:hover:bg-transparent transition-colors">
                            ← {text.previous}
                          </button>
                          <span className="text-sm font-medium text-gray-700 dark:text-zinc-200">{text.slideLabel} {currentSlide + 1} / {previewImages.length}</span>
                          <button onClick={() => setCurrentSlide(p => Math.min(previewImages.length - 1, p + 1))} disabled={currentSlide === previewImages.length - 1}
                            className="px-3 py-1 rounded text-sm text-gray-600 dark:text-zinc-300 hover:bg-gray-200 dark:hover:bg-zinc-700 disabled:text-gray-300 dark:disabled:text-zinc-600 disabled:hover:bg-transparent dark:disabled:hover:bg-transparent transition-colors">
                            {text.next} →
                          </button>
                        </div>
                        <div className="p-4 flex justify-center">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={previewImages[currentSlide]}
                            alt={`${text.slideImage} ${currentSlide + 1}`}
                            className="max-w-full h-auto rounded-lg shadow-sm"
                            style={{ maxHeight: '50vh' }}
                          />
                        </div>

                        {/* Editable text below the image */}
                        {document && document.slides[currentSlide] && (
                          <div className="px-5 pb-4 border-t border-gray-200 dark:border-zinc-800">
                            <div className="pt-4 space-y-3 max-h-64 overflow-y-auto">
                              {getSlideTextEntries(currentSlide).map((entry, i) => (
                                <div key={entry.run.run_id} className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
                                  <div>
                                    <div className="text-[10px] text-gray-400 dark:text-zinc-500 mb-0.5">{text.original}</div>
                                    <div className="bg-gray-50 dark:bg-zinc-800/60 rounded-lg px-3 py-2 text-gray-600 dark:text-zinc-300 border border-gray-100 dark:border-zinc-700 leading-relaxed text-xs">
                                      {entry.run.text || <span className="text-gray-300 dark:text-zinc-600 italic">—</span>}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-[10px] text-gray-400 dark:text-zinc-500 mb-0.5">{text.translation}</div>
                                    <input type="text" value={entry.tr?.translated_text || ''}
                                      onChange={e => handleTextEdit(entry.run.run_id, e.target.value)}
                                      className={`w-full text-xs rounded-lg px-3 py-2 border transition-colors focus:outline-none focus:ring-1 ${
                                        entry.isFailed
                                          ? 'bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-900 text-red-600 dark:text-red-300 focus:border-red-400'
                                          : 'bg-white dark:bg-zinc-900 border-gray-200 dark:border-zinc-700 text-gray-700 dark:text-zinc-200 focus:border-blue-500 focus:ring-blue-500'
                                      }`} />
                                  </div>
                                </div>
                              ))}
                              {getSlideTextEntries(currentSlide).length === 0 && (
                                <p className="text-xs text-gray-400 dark:text-zinc-500 italic py-2">{text.original === 'Original' ? 'No text on this slide' : 'このスライドにテキストはありません'}</p>
                              )}
                            </div>
                          </div>
                        )}

                      </div>
                    </div>
                  )}

                  {/* Slide check — opt-in, report-only. Its own model list: the
                      translation models cannot read images at all. */}
                  {document && (
                    <div className="border-t border-gray-200 dark:border-zinc-800 pt-5">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <h3 className="text-sm font-medium text-gray-700 dark:text-zinc-200">{text.slideCheck}</h3>
                          <p className="text-xs text-gray-400 dark:text-zinc-500 mt-0.5">{text.slideCheckOptIn}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <select value={visionModel} onChange={e => setVisionModel(e.target.value)}
                            aria-label={text.slideCheckModel}
                            className="border border-gray-300 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 appearance-none cursor-pointer">
                            {(catalog?.vision || []).map(m => (
                              <option key={m.model} value={m.model}>
                                {m.model === catalog?.defaults.vision ? '★ ' : ''}{m.label}
                              </option>
                            ))}
                          </select>
                          <button onClick={() => runSlideCheck(document.job_id)} disabled={qaRunning || !visionModel}
                            className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 dark:disabled:bg-zinc-700 disabled:text-gray-500 dark:disabled:text-zinc-500 transition-colors">
                            {qaRunning ? text.checking : text.runSlideCheck}
                          </button>
                        </div>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-zinc-400 mt-2 leading-relaxed">{text.slideCheckHint}</p>

                      {qaRunning && qaProgress && (
                        <p className="mt-2 text-xs text-indigo-600 dark:text-indigo-400">
                          {text.slideCheckProgress} {qaProgress.checked}
                          {qaProgress.total ? ` / ${qaProgress.total}` : ''}…
                        </p>
                      )}

                      {qaError && (
                        <div className="mt-3 px-4 py-2.5 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-lg text-sm text-red-700 dark:text-red-300">{qaError}</div>
                      )}

                      {qaReport && (
                        <div className="mt-3">
                          <div className="flex flex-wrap items-center gap-2 text-xs">
                            <span className="text-gray-600 dark:text-zinc-300 bg-gray-100 dark:bg-zinc-800 px-2.5 py-1 rounded-full">{qaReport.summary}</span>
                            {qaReport.model && <span className="text-gray-400 dark:text-zinc-500">{qaReport.model}</span>}
                          </div>

                          {/* Not while a later chunk may still turn something up: a
                              green "nothing found" after chunk 1 of 20 is a lie. */}
                          {!qaRunning && qaReport.issues.length === 0 && !(qaReport.errors || []).length && (
                            <p className="mt-2 text-sm text-green-700 dark:text-green-300">{text.slideCheckClean}</p>
                          )}

                          {qaReport.issues.map((issue, i) => (
                            <div key={i} className={`mt-2 px-4 py-3 rounded-lg border text-sm ${
                              issue.severity === 'high'
                                ? 'bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-900'
                                : issue.severity === 'medium'
                                  ? 'bg-yellow-50 dark:bg-yellow-950/40 border-yellow-200 dark:border-yellow-900'
                                  : 'bg-gray-50 dark:bg-zinc-900 border-gray-200 dark:border-zinc-800'
                            }`}>
                              <div className="flex items-center gap-2 text-xs mb-1">
                                <span className="font-medium text-gray-700 dark:text-zinc-200">{text.slideLabel} {issue.slide}</span>
                                <span className="uppercase tracking-wider text-gray-500 dark:text-zinc-400">{issue.severity} · {issue.type}</span>
                              </div>
                              {issue.where && <div className="text-gray-700 dark:text-zinc-200 text-xs font-medium">{issue.where}</div>}
                              {issue.detail && <div className="text-gray-600 dark:text-zinc-300 text-xs mt-0.5 leading-relaxed">{issue.detail}</div>}
                            </div>
                          ))}

                          {(qaReport.errors || []).length > 0 && (
                            <div className="mt-2 px-4 py-3 rounded-lg border border-orange-200 dark:border-orange-900 bg-orange-50 dark:bg-orange-950/40">
                              <div className="text-xs font-medium text-orange-700 dark:text-orange-300 mb-1">{text.slideCheckErrored}</div>
                              <ul className="text-xs text-orange-700 dark:text-orange-300 space-y-0.5">
                                {(qaReport.errors || []).map((err, i) => (
                                  <li key={i}>{text.slideLabel} {err.slide}: {err.error}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-100 dark:border-zinc-800 py-4 mt-auto">
        <div className="max-w-5xl mx-auto px-6 flex items-center justify-between text-xs text-gray-400 dark:text-zinc-500">
          <span>{text.title}</span>
          {document && <span className="text-gray-300 dark:text-zinc-600">{document.job_id}</span>}
          {!document && restoreJobId && (
            <button onClick={() => { try { localStorage.removeItem('jpeigo-last-job-id'); } catch(e){/*no-op*/} setRestoreJobId(null); }} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">Dismiss previous session</button>
          )}
        </div>
      </footer>
    </div>
  );
}
