'use client';

import React, { useState, useCallback, useEffect } from 'react';

// ──────────────────────────────────────────────────────────────────
//  Types
// ──────────────────────────────────────────────────────────────────

interface SlidesPresentation {
  id: string;
  name: string;
  modifiedTime?: string;
  owners?: { displayName: string }[];
}

interface SlidesExtractResult {
  presentation_id: string;
  title: string;
  total_slides: number;
  total_runs: number;
  slides: { slide_index: number; slide_object_id: string; text_boxes: { page_element_id: string; shape_type: string; runs: { run_id: string; text: string; style: Record<string, unknown> }[] }[] }[];
  runs: { run_id: string; text: string; style: Record<string, unknown> }[];
}

interface SlidesTranslateResult {
  new_presentation_id: string;
  new_title: string;
  new_url: string;
  total_runs: number;
  translated_runs: number;
  model_used: string;
}

type SlidesPhase = 'idle' | 'auth_check' | 'listing' | 'selecting' | 'loading' | 'ready' | 'translating' | 'done' | 'error';

// ──────────────────────────────────────────────────────────────────
//  Props
// ──────────────────────────────────────────────────────────────────

interface SlidesPanelProps {
  ui: 'en' | 'ja';
  sourceLang: 'ja' | 'en';
  targetLang: 'ja' | 'en';
  model: string;
  contextPrompt: string;
}

const text = (ui: 'en' | 'ja') =>
  ui === 'en'
    ? {
        connect: 'Connect Google Slides',
        connecting: 'Connecting...',
        connected: '✅ Connected',
        disconnect: 'Disconnect',
        selectPresentation: 'Select a presentation to translate',
        loadingPresentations: 'Loading presentations...',
        noPresentations: 'No presentations found in your Drive',
        name: 'Name',
        modified: 'Modified',
        slides: 'slides',
        runs: 'text runs',
        readyToTranslate: 'Ready to translate',
        totalRuns: 'total text runs',
        translateToSlides: 'Translate & Create Slides',
        translating: 'Translating...',
        translated: 'Translation complete!',
        openInSlides: 'Open in Google Slides',
        newTitle: 'Translated copy title (optional)',
        newTitlePlaceholder: 'e.g., My Deck (English)',
        startOver: 'Start over',
        authenticateFirst: 'Connect your Google account to get started.',
        extractText: 'Extracting text from presentation...',
        content: 'Content',
        noTextRuns: 'No text content found in this presentation.',
        authError: 'Authentication failed. Please try again.',
        listError: 'Could not load presentations. Check your connection.',
        translateError: 'Translation failed. Please try again.',
        connectLink: 'Click to connect →',
      }
    : {
        connect: 'Google Slidesに接続',
        connecting: '接続中...',
        connected: '✅ 接続済み',
        disconnect: '切断',
        selectPresentation: '翻訳するプレゼンテーションを選択',
        loadingPresentations: 'プレゼンテーションを読み込み中...',
        noPresentations: 'Driveにプレゼンテーションが見つかりません',
        name: '名前',
        modified: '更新日',
        slides: 'スライド',
        runs: 'テキスト',
        readyToTranslate: '翻訳準備完了',
        totalRuns: 'テキスト数',
        translateToSlides: '翻訳してSlidesを作成',
        translating: '翻訳中...',
        translated: '翻訳完了！',
        openInSlides: 'Google Slidesで開く',
        newTitle: '翻訳後のタイトル（任意）',
        newTitlePlaceholder: '例：提案書（英語版）',
        startOver: '最初から',
        authenticateFirst: 'Googleアカウントに接続してください。',
        extractText: 'プレゼンテーションからテキストを抽出中...',
        content: '内容',
        noTextRuns: 'このプレゼンテーションにテキストが見つかりません。',
        authError: '認証に失敗しました。もう一度お試しください。',
        listError: 'プレゼンテーションを読み込めませんでした。',
        translateError: '翻訳に失敗しました。もう一度お試しください。',
        connectLink: 'クリックして接続 →',
      };

// ──────────────────────────────────────────────────────────────────
//  Component
// ──────────────────────────────────────────────────────────────────

export default function SlidesPanel({ ui, sourceLang, targetLang, model, contextPrompt }: SlidesPanelProps) {
  const t = text(ui);
  const [phase, setPhase] = useState<SlidesPhase>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [presentations, setPresentations] = useState<SlidesPresentation[]>([]);
  const [selectedPres, setSelectedPres] = useState<SlidesPresentation | null>(null);
  const [extractResult, setExtractResult] = useState<SlidesExtractResult | null>(null);
  const [translateResult, setTranslateResult] = useState<SlidesTranslateResult | null>(null);
  const [newTitle, setNewTitle] = useState('');

  // Check auth status on mount
  useEffect(() => {
    checkAuth();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const checkAuth = async () => {
    try {
      const res = await fetch('/api/slides/auth/status');
      const data = await res.json();
      if (data.authenticated) {
        setPhase('selecting');
        loadPresentations();
      } else {
        setPhase('idle');
      }
    } catch {
      setPhase('idle');
    }
  };

  const handleConnect = async () => {
    setPhase('auth_check');
    setErrorMsg(null);
    try {
      const res = await fetch('/api/slides/auth/url');
      const data = await res.json();
      if (data.url) {
        // Redirect browser to Google OAuth
        window.location.href = data.url;
      } else {
        setPhase('idle');
        setErrorMsg(t.authError);
      }
    } catch {
      setPhase('idle');
      setErrorMsg(t.authError);
    }
  };

  const handleDisconnect = async () => {
    await fetch('/api/slides/auth/logout', { method: 'POST' });
    setPhase('idle');
    setPresentations([]);
    setSelectedPres(null);
    setExtractResult(null);
    setTranslateResult(null);
  };

  const loadPresentations = async () => {
    setPhase('listing');
    setErrorMsg(null);
    try {
      const res = await fetch('/api/slides/presentations');
      if (res.status === 401) {
        setPhase('idle');
        setErrorMsg(t.authError);
        return;
      }
      if (!res.ok) {
        setPhase('error');
        setErrorMsg(t.listError);
        return;
      }
      const data = await res.json();
      setPresentations(data.presentations || []);
      setPhase('selecting');
    } catch {
      setPhase('error');
      setErrorMsg(t.listError);
    }
  };

  const handleSelectPresentation = async (pres: SlidesPresentation) => {
    setSelectedPres(pres);
    setExtractResult(null);
    setTranslateResult(null);
    setPhase('loading');
    setErrorMsg(null);
    setNewTitle(`Translated - ${pres.name}`);

    try {
      const res = await fetch(`/api/slides/read/${encodeURIComponent(pres.id)}`);
      if (!res.ok) {
        setPhase('error');
        setErrorMsg(t.listError);
        return;
      }
      const data: SlidesExtractResult = await res.json();
      setExtractResult(data);
      setPhase('ready');
    } catch {
      setPhase('error');
      setErrorMsg(t.extractText + ' ' + t.listError);
    }
  };

  const handleTranslateToSlides = async () => {
    if (!selectedPres || !extractResult) return;
    setPhase('translating');
    setErrorMsg(null);

    try {
      const res = await fetch('/api/slides/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          presentation_id: selectedPres.id,
          source_language: sourceLang,
          target_language: targetLang,
          model,
          context: contextPrompt || null,
          new_title: newTitle || null,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setPhase('error');
        setErrorMsg(errData.error || t.translateError);
        return;
      }

      const result: SlidesTranslateResult = await res.json();
      setTranslateResult(result);
      setPhase('done');
    } catch {
      setPhase('error');
      setErrorMsg(t.translateError);
    }
  };

  const handleStartOver = () => {
    setSelectedPres(null);
    setExtractResult(null);
    setTranslateResult(null);
    setErrorMsg(null);
    setPhase('selecting');
  };

  // ────────────────────────────────────────────────────────────
  //  Helpers
  // ────────────────────────────────────────────────────────────

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '';
    try {
      return new Date(dateStr).toLocaleDateString(ui === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric', month: 'short', day: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  // ────────────────────────────────────────────────────────────
  //  Render
  // ────────────────────────────────────────────────────────────

  if (phase === 'idle') {
    return (
      <div className="max-w-xl mx-auto mt-8">
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-50 mb-4">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1a73e8" strokeWidth="1.5">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <h2 className="text-lg font-medium text-gray-800 mb-2">Google Slides</h2>
          <p className="text-sm text-gray-500 mb-5">{t.authenticateFirst}</p>
          <button onClick={handleConnect}
            className="px-6 py-2.5 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 transition-colors shadow-sm inline-flex items-center gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            {t.connect}
          </button>
          {errorMsg && <p className="mt-4 text-sm text-red-600">{errorMsg}</p>}
        </div>
      </div>
    );
  }

  if (phase === 'auth_check') {
    return (
      <div className="max-w-xl mx-auto mt-8">
        <div className="bg-white border border-gray-200 rounded-xl p-6 text-center">
          <svg className="animate-spin h-6 w-6 text-blue-500 mx-auto mb-3" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-sm text-gray-500">{t.connecting}</p>
        </div>
      </div>
    );
  }

  // ── Presentation list / selection ──
  if (phase === 'listing' || phase === 'selecting') {
    return (
      <div className="max-w-2xl mx-auto mt-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-medium text-gray-700">{t.selectPresentation}</h2>
          <button onClick={handleDisconnect} className="text-xs text-gray-400 hover:text-red-500 transition-colors">
            {t.disconnect}
          </button>
        </div>

        {phase === 'listing' ? (
          <div className="bg-white border border-gray-200 rounded-xl p-6 text-center">
            <svg className="animate-spin h-5 w-5 text-blue-500 mx-auto mb-2" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-sm text-gray-500">{t.loadingPresentations}</p>
          </div>
        ) : presentations.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl p-8 text-center">
            <p className="text-sm text-gray-500">{t.noPresentations}</p>
            <button onClick={loadPresentations} className="mt-3 text-sm text-blue-600 hover:underline">
              {ui === 'en' ? 'Refresh' : '更新'}
            </button>
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {presentations.map((pres) => (
              <button
                key={pres.id}
                onClick={() => handleSelectPresentation(pres)}
                className="w-full text-left bg-white border border-gray-200 hover:border-blue-300 hover:bg-blue-50/30 rounded-xl p-4 transition-all"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-800 truncate">{pres.name}</p>
                    <p className="text-xs text-gray-400 mt-1">
                      {formatDate(pres.modifiedTime)}
                      {pres.owners?.[0] && ` · ${pres.owners[0].displayName}`}
                    </p>
                  </div>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9aa0a6" strokeWidth="1.5" className="flex-shrink-0 mt-0.5">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ── Loading / extracting ──
  if (phase === 'loading') {
    return (
      <div className="max-w-xl mx-auto mt-8">
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          {selectedPres && <p className="text-sm font-medium text-gray-700 mb-4 truncate">{selectedPres.name}</p>}
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full animate-pulse" style={{ width: '60%' }} />
          </div>
          <p className="text-xs text-gray-400 mt-3">{t.extractText}</p>
        </div>
      </div>
    );
  }

  // ── Ready to translate ──
  if (phase === 'ready' && extractResult && selectedPres) {
    return (
      <div className="max-w-2xl mx-auto mt-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-medium text-gray-700 truncate">{selectedPres.name}</h2>
            <p className="text-xs text-gray-400">{extractResult.total_slides} {t.slides} · {extractResult.total_runs} {t.runs}</p>
          </div>
          <button onClick={handleStartOver} className="text-xs text-blue-600 hover:underline flex-shrink-0 ml-3">
            {t.startOver}
          </button>
        </div>

        {/* Content preview */}
        <div className="bg-white border border-gray-200 rounded-xl p-4 mb-4 max-h-48 overflow-y-auto">
          <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">{t.content}</h3>
          {extractResult.runs.length > 0 ? (
            <div className="space-y-1">
              {extractResult.runs.slice(0, 30).map((run, i) => (
                <p key={run.run_id} className="text-xs text-gray-600 leading-relaxed">
                  <span className="text-gray-300 mr-1">[{run.text.length}c]</span>
                  {run.text.length > 80 ? run.text.slice(0, 80) + '...' : run.text}
                </p>
              ))}
              {extractResult.runs.length > 30 && (
                <p className="text-xs text-gray-400 italic mt-1">
                  ...and {extractResult.runs.length - 30} more {t.runs}
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-400 italic">{t.noTextRuns}</p>
          )}
        </div>

        {/* New title */}
        <div className="mb-4">
          <label className="block text-xs text-gray-500 mb-1">{t.newTitle}</label>
          <input type="text" value={newTitle} onChange={e => setNewTitle(e.target.value)}
            placeholder={t.newTitlePlaceholder}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500" />
        </div>

        {/* Translate button */}
        <button onClick={handleTranslateToSlides}
          className="w-full px-6 py-3 rounded-xl text-sm font-medium text-white bg-green-600 hover:bg-green-700 transition-colors shadow-sm">
          {t.translateToSlides} ({extractResult.total_runs} {t.runs})
        </button>

        {errorMsg && <p className="mt-3 text-sm text-red-600">{errorMsg}</p>}
      </div>
    );
  }

  // ── Translating ──
  if (phase === 'translating') {
    return (
      <div className="max-w-xl mx-auto mt-8">
        <div className="bg-white border border-gray-200 rounded-xl p-6 text-center">
          <svg className="animate-spin h-6 w-6 text-green-500 mx-auto mb-3" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-sm text-gray-600">{t.translating}</p>
          {selectedPres && <p className="text-xs text-gray-400 mt-1">{selectedPres.name}</p>}
        </div>
      </div>
    );
  }

  // ── Done ──
  if (phase === 'done' && translateResult) {
    return (
      <div className="max-w-xl mx-auto mt-8">
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-green-50 mb-4">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <h2 className="text-lg font-medium text-gray-800 mb-1">{t.translated}</h2>
          <p className="text-sm text-gray-500 mb-2">
            {translateResult.translated_runs}/{translateResult.total_runs} {t.runs}
            {' · '}{translateResult.model_used}
          </p>
          <p className="text-sm text-gray-700 mb-6 truncate">{translateResult.new_title}</p>

          <a href={translateResult.new_url} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-medium text-white bg-green-600 hover:bg-green-700 transition-colors shadow-sm">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
            </svg>
            {t.openInSlides}
          </a>

          <div className="mt-6 flex justify-center gap-3">
            <button onClick={handleStartOver}
              className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:text-gray-800 border border-gray-300 hover:border-gray-400 transition-colors">
              {t.startOver}
            </button>
            <button onClick={handleDisconnect}
              className="px-4 py-2 rounded-lg text-sm font-medium text-gray-400 hover:text-red-500 border border-gray-200 hover:border-red-200 transition-colors">
              {t.disconnect}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Error ──
  return (
    <div className="max-w-xl mx-auto mt-8">
      <div className="bg-white border border-red-200 rounded-xl p-6 text-center">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-red-50 mb-3">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="1.5">
            <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
          </svg>
        </div>
        <p className="text-sm text-red-600 mb-4">{errorMsg || t.translateError}</p>
        <div className="flex justify-center gap-3">
          <button onClick={handleStartOver}
            className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 border border-gray-300 hover:border-gray-400 transition-colors">
            {t.startOver}
          </button>
          <button onClick={checkAuth}
            className="px-4 py-2 rounded-lg text-sm font-medium text-blue-600 border border-blue-200 hover:bg-blue-50 transition-colors">
            {ui === 'en' ? 'Retry' : '再試行'}
          </button>
        </div>
      </div>
    </div>
  );
}
