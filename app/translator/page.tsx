'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import SlidesPanel from '@/components/SlidesPanel';

// --- Types ---
interface TextRun { run_id: string; text: string; style: { font_size: number | null; font_color: string | null; font_name: string | null; bold: boolean; italic: boolean; underline: boolean; }; }
interface TextBox { box_id: string; shape_type: string; runs: TextRun[]; constraints: { left: number; top: number; width: number; height: number; }; }
interface Slide { slide_index: number; slide_id: number; text_boxes: TextBox[]; }
interface UploadedDocument { job_id: string; filename: string; total_slides: number; total_text_boxes: number; total_runs: number; slides: Slide[]; }
interface TranslatedRun { run_id: string; original_text: string; translated_text: string; source_language: string; target_language: string; model_used: string; adjusted_font_size: number | null; }
interface HealthStatus { settings: Record<string, boolean | string>; }

// --- i18n ---
type UI = 'en' | 'ja';
const en = {
  title: 'PPTX Translator',
  subtitle: 'Translate PowerPoint slides',
  desc: 'Upload a .pptx file to extract and translate text while preserving formatting.',
  uploadPrompt: 'Drag a file here or click to browse',
  uploadHint: '.pptx files up to 50MB',
  extracting: 'Extracting text from PowerPoint...',
  from: 'From', to: 'To',
  model: 'Translation model',
  context: 'Translation context (optional)',
  contextPlaceholder: 'e.g., formal business tone, technical terminology',
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
  slideImage: 'Slide image',
  previous: 'Previous', next: 'Next',
  renderingPreview: 'Rendering slides...',
};
const ja: typeof en = {
  title: 'PPTX翻訳',
  subtitle: 'PowerPointスライドを翻訳',
  desc: 'pptxファイルをアップロードして、テキストを抽出・翻訳。フォーマットはそのまま保持します。',
  uploadPrompt: 'ファイルをドラッグ＆ドロップ、またはクリックして選択',
  uploadHint: '.pptx ファイル（50MBまで）',
  extracting: 'PowerPointからテキストを抽出中...',
  from: '翻訳元', to: '翻訳先',
  model: '翻訳モデル',
  context: '翻訳コンテキスト（任意）',
  contextPlaceholder: '例：フォーマルなビジネス文書、技術用語を多用',
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
  slideImage: 'スライド画像',
  previous: '前へ', next: '次へ',
  renderingPreview: 'スライドをレンダリング中...',
};
const t = (ui: UI) => ui === 'en' ? en : ja;

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
  const [model, setModel] = useState<string>('gemini-flash-lite');
  const [contextPrompt, setContextPrompt] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Preview state
  const [previewImages, setPreviewImages] = useState<string[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [currentSlide, setCurrentSlide] = useState(0);

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
  const generatePreview = useCallback(async (jobId: string, filename: string) => {
    setPreviewLoading(true);
    setPreviewError(null);
    setCurrentSlide(0);
    try {
      const res = await fetch('/api/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, filename }),
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

  const handleFile = useCallback(async (file: File) => {
    if (!file.name.endsWith('.pptx')) { setError(text.onlyPptx); return; }
    setLoading(true); setError(null); setProgress(0); setTranslatedRuns([]);
    setPreviewImages([]); setPreviewError(null);
    try {
      const formData = new FormData(); formData.append('file', file);
      const response = await fetch('/api/upload-new', { method: 'POST', body: formData });
      if (!response.ok) { const err = await response.json().catch(() => ({ error: text.uploadFailed })); throw new Error(err.error || text.uploadFailed); }
      const data = await response.json(); setDocument(data); setProgress(100);
    } catch (err) { setError(err instanceof Error ? err.message : text.uploadFailed); }
    finally { setLoading(false); }
  }, [ui]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDrop = useCallback((e: React.DragEvent) => { e.preventDefault(); setDragOver(false); const file = e.dataTransfer.files?.[0]; if (file) handleFile(file); }, [handleFile]);

  const handleTranslate = useCallback(async () => {
    if (!document) return;
    setTranslating(true); setError(null); setApiError(null); setProgress(0);
    setPreviewImages([]); setPreviewError(null);
    try {
      const allRuns: TextRun[] = [];
      for (const slide of document.slides) for (const textBox of slide.text_boxes) allRuns.push(...textBox.runs);
      if (allRuns.length === 0) throw new Error(text.noText);
      const body: Record<string, unknown> = { runs: allRuns, source_language: sourceLang, target_language: targetLang, model, job_id: document.job_id };
      if (contextPrompt.trim()) body.context = contextPrompt.trim();
      const response = await fetch('/api/translate-new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) { const err = await response.json().catch(() => ({ error: text.translationFailed })); throw new Error(err.error || text.translationFailed); }
      const data = await response.json();
      setTranslatedRuns(data.translated_runs || []);
      const failed = (data.translated_runs || []).filter((r: TranslatedRun) => r.original_text === r.translated_text && r.model_used !== 'cache');
      if (failed.length > 0) setApiError(`${failed.length} of ${data.translated_runs.length} runs couldn't be translated.`);
      setProgress(100);

      // Auto-generate preview images
      generatePreview(document.job_id, document.filename);
    } catch (err) { setError(err instanceof Error ? err.message : text.translationFailed); }
    finally { setTranslating(false); }
  }, [document, sourceLang, targetLang, model, contextPrompt, ui]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleExport = useCallback(async () => {
    if (!document || translatedRuns.length === 0) return;
    setExporting(true); setError(null);
    try {
      const response = await fetch('/api/export-new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: document.job_id, filename: `translated_${document.filename}` }) });
      if (!response.ok) { const err = await response.json().catch(() => ({ error: text.exportFailed })); throw new Error(err.error || text.exportFailed); }
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
    <div className="min-h-screen bg-white flex flex-col">
      {/* --- Header --- */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="#5f6368">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
            </svg>
            <span className="text-sm font-medium text-gray-700 select-none">{text.title}</span>
          </div>
          <div className="flex items-center gap-4 text-sm">
            {/* Mode Toggle: PPTX vs Google Slides */}
            <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
              <button onClick={() => { setMode('pptx'); resetAll(); }} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${mode === 'pptx' ? 'bg-white text-gray-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" className="inline-block mr-1 -mt-0.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                PPTX
              </button>
              <button onClick={() => { setMode('slides'); resetAll(); }} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${mode === 'slides' ? 'bg-white text-gray-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" className="inline-block mr-1 -mt-0.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
                Slides
              </button>
            </div>
            {/* EN/JP Toggle */}
            <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
              <button onClick={() => setUi('en')} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${ui === 'en' ? 'bg-white text-gray-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>EN</button>
              <button onClick={() => setUi('ja')} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${ui === 'ja' ? 'bg-white text-gray-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>JP</button>
            </div>
            {health && (
              <span className="flex items-center gap-1.5 text-gray-500">
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
            <div className="mb-6 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>
          )}

          {/* === Upload State (PPTX mode) === */}
          {mode === 'pptx' && !document && !loading && (
            <div className="max-w-xl mx-auto mt-12">
              <div className="text-center mb-8">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-50 mb-4">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1a73e8" strokeWidth="1.5">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="12" y1="18" x2="12" y2="12" />
                    <line x1="9" y1="15" x2="15" y2="15" />
                  </svg>
                </div>
                <h1 className="text-2xl font-normal text-gray-800 mb-2">{text.subtitle}</h1>
                <p className="text-sm text-gray-500">{text.desc}</p>
              </div>
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-xl py-16 px-8 text-center cursor-pointer transition-all ${
                  dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400 bg-gray-50/30 hover:bg-gray-50'
                }`}
              >
                <input ref={fileInputRef} type="file" accept=".pptx" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#9aa0a6" strokeWidth="1.5" className="mx-auto mb-3">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                <p className="text-sm font-medium text-gray-700 mb-0.5">{text.uploadPrompt}</p>
                <p className="text-xs text-gray-400">{text.uploadHint}</p>
              </div>
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
              <div className="bg-white border border-gray-200 rounded-xl p-6">
                <div className="flex items-center justify-between mb-3 text-sm">
                  <span className="text-gray-600">{text.extracting}</span>
                  <span className="text-blue-600 font-medium">{progress}%</span>
                </div>
                <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 rounded-full transition-all duration-500 ease-out" style={{ width: `${progress}%` }} />
                </div>
              </div>
            </div>
          )}

          {/* === Translate / Review State === */}
          {document && !loading && (
            <>
              {/* File info bar */}
              <div className="flex items-center gap-2.5 mb-8 pb-5 border-b border-gray-200">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5f6368" strokeWidth="1.5">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                <span className="text-sm text-gray-700 truncate">{fileInfo}</span>
              </div>

              {/* Two column: Settings */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                {/* Languages */}
                <div className="bg-gray-50/50 border border-gray-200 rounded-xl p-5">
                  <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-4">{ui === 'en' ? 'Languages' : '言語設定'}</h3>
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <label className="block text-xs text-gray-500 mb-1">{text.from}</label>
                      <select value={sourceLang} onChange={e => setSourceLang(e.target.value as 'ja' | 'en')}
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white text-gray-700 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 appearance-none cursor-pointer">
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
                      <label className="block text-xs text-gray-500 mb-1">{text.to}</label>
                      <select value={targetLang} onChange={e => setTargetLang(e.target.value as 'ja' | 'en')}
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white text-gray-700 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 appearance-none cursor-pointer">
                        <option value="ja">Japanese</option>
                        <option value="en">English</option>
                      </select>
                    </div>
                  </div>
                </div>
                <div className="bg-gray-50/50 border border-gray-200 rounded-xl p-5">
                  <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-4">{text.model}</h3>
                  <select value={model} onChange={e => setModel(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white text-gray-700 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 appearance-none cursor-pointer mb-3">
                    <optgroup label="Google Gemini">
                      <option value="gemini-pro">Gemini 3 Pro</option>
                      <option value="gemini-flash">Gemini 3.5 Flash</option>
                      <option value="gemini-flash-lite">Gemini 3.1 Flash Lite</option>
                      <option value="gemini-25-flash-lite">Gemini 2.5 Flash Lite</option>
                    </optgroup>
                    <optgroup label="OpenCode">
                      <option value="opencode-deepseek">DeepSeek V4</option>
                      <option value="opencode-kimi">Kimi K2.5</option>
                      <option value="opencode-qwen">Qwen Max</option>
                      <option value="opencode-minimax">MiniMax M2.5</option>
                    </optgroup>
                  </select>
                  <input type="text" value={contextPrompt} onChange={e => setContextPrompt(e.target.value)}
                    placeholder={text.contextPlaceholder}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500" />
                </div>
              </div>

              {apiError && (
                <div className="mb-4 px-4 py-2.5 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-700">{apiError}</div>
              )}

              {/* Translate button + progress */}
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <button onClick={handleTranslate} disabled={translating}
                    className="px-6 py-2.5 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:text-gray-500 transition-colors shadow-sm">
                    {translating ? text.translating : text.translate}
                  </button>
                  {allDone && (
                    <button onClick={handleExport} disabled={exporting}
                      className="px-6 py-2.5 rounded-lg text-sm font-medium text-white bg-green-600 hover:bg-green-700 disabled:bg-gray-300 transition-colors shadow-sm">
                      {exporting ? text.downloading : text.download}
                    </button>
                  )}
                  <button onClick={resetAll}
                    className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-600 hover:text-gray-800 border border-gray-300 hover:border-gray-400 transition-colors">
                    {text.startOver}
                  </button>
                </div>
                {allDone && translatedRuns.length > 0 && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-green-700 bg-green-50 px-2.5 py-1 rounded-full">{completedCount}/{translatedRuns.length} {text.done}</span>
                    {failedCount > 0 && <span className="text-yellow-700 bg-yellow-50 px-2.5 py-1 rounded-full">{failedCount} {text.failed}</span>}
                  </div>
                )}
              </div>

              {translating && (
                <div className="mb-6">
                  <div className="flex items-center justify-between text-sm mb-2">
                    <span className="text-gray-500">{text.translating}</span>
                    <span className="text-blue-600 font-medium">{progress}%</span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full transition-all duration-500 ease-out" style={{ width: `${progress}%` }} />
                  </div>
                </div>
              )}

              {/* === Preview Images === */}
              {allDone && (
                <div className="mt-8 border-t border-gray-200 pt-8">
                  <h2 className="text-base font-medium text-gray-700 mb-4">{text.previewSlides}</h2>

                  {/* Loading preview */}
                  {previewLoading && (
                    <div className="bg-gray-50 border border-gray-200 rounded-xl p-8 text-center">
                      <svg className="animate-spin h-6 w-6 text-blue-500 mx-auto mb-3" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <p className="text-sm text-gray-500">{text.generatingPreview}</p>
                      <p className="text-xs text-gray-400 mt-1">{text.renderingPreview}</p>
                    </div>
                  )}

                  {/* Preview error */}
                  {previewError && !previewLoading && (
                    <div className="px-4 py-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-700">{previewError}</div>
                  )}

                  {/* Image viewer */}
                  {previewImages.length > 0 && !previewLoading && (
                    <div>
                      {/* Slide selector dots */}
                      <div className="flex items-center justify-center gap-2 mb-4">
                        {previewImages.map((_, i) => (
                          <button key={i} onClick={() => setCurrentSlide(i)}
                            className={`w-2 h-2 rounded-full transition-colors ${i === currentSlide ? 'bg-blue-600' : 'bg-gray-300 hover:bg-gray-400'}`}
                            aria-label={`${text.slideLabel} ${i + 1}`} />
                        ))}
                      </div>

                      {/* Current slide image */}
                      <div className="bg-gray-50 border border-gray-200 rounded-xl overflow-hidden">
                        <div className="bg-gray-100 px-4 py-2 border-b border-gray-200 flex items-center justify-between">
                          <button onClick={() => setCurrentSlide(p => Math.max(0, p - 1))} disabled={currentSlide === 0}
                            className="px-3 py-1 rounded text-sm text-gray-600 hover:bg-gray-200 disabled:text-gray-300 disabled:hover:bg-transparent transition-colors">
                            ← {text.previous}
                          </button>
                          <span className="text-sm font-medium text-gray-700">{text.slideLabel} {currentSlide + 1} / {previewImages.length}</span>
                          <button onClick={() => setCurrentSlide(p => Math.min(previewImages.length - 1, p + 1))} disabled={currentSlide === previewImages.length - 1}
                            className="px-3 py-1 rounded text-sm text-gray-600 hover:bg-gray-200 disabled:text-gray-300 disabled:hover:bg-transparent transition-colors">
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
                          <div className="px-5 pb-4 border-t border-gray-200">
                            <div className="pt-4 space-y-3 max-h-64 overflow-y-auto">
                              {getSlideTextEntries(currentSlide).map((entry, i) => (
                                <div key={entry.run.run_id} className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
                                  <div>
                                    <div className="text-[10px] text-gray-400 mb-0.5">{text.original}</div>
                                    <div className="bg-gray-50 rounded-lg px-3 py-2 text-gray-600 border border-gray-100 leading-relaxed text-xs">
                                      {entry.run.text || <span className="text-gray-300 italic">—</span>}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-[10px] text-gray-400 mb-0.5">{text.translation}</div>
                                    <input type="text" value={entry.tr?.translated_text || ''}
                                      onChange={e => handleTextEdit(entry.run.run_id, e.target.value)}
                                      className={`w-full text-xs rounded-lg px-3 py-2 border transition-colors focus:outline-none focus:ring-1 ${
                                        entry.isFailed
                                          ? 'bg-red-50 border-red-200 text-red-600 focus:border-red-400'
                                          : 'bg-white border-gray-200 text-gray-700 focus:border-blue-500 focus:ring-blue-500'
                                      }`} />
                                  </div>
                                </div>
                              ))}
                              {getSlideTextEntries(currentSlide).length === 0 && (
                                <p className="text-xs text-gray-400 italic py-2">{text.original === 'Original' ? 'No text on this slide' : 'このスライドにテキストはありません'}</p>
                              )}
                            </div>
                          </div>
                        )}

                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-100 py-4 mt-auto">
        <div className="max-w-5xl mx-auto px-6 flex items-center justify-between text-xs text-gray-400">
          <span>{text.title}</span>
          {document && <span className="text-gray-300">{document.job_id}</span>}
        </div>
      </footer>
    </div>
  );
}
