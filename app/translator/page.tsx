'use client';

import React, { useState, useCallback } from 'react';

interface TextRun {
  run_id: string;
  text: string;
  style: {
    font_size: number | null;
    font_color: string | null;
    font_name: string | null;
    bold: boolean;
    italic: boolean;
    underline: boolean;
  };
}

interface TextBox {
  box_id: string;
  shape_type: string;
  runs: TextRun[];
  constraints: {
    left: number;
    top: number;
    width: number;
    height: number;
  };
}

interface Slide {
  slide_index: number;
  slide_id: number;
  text_boxes: TextBox[];
}

interface UploadedDocument {
  job_id: string;
  filename: string;
  total_slides: number;
  total_text_boxes: number;
  total_runs: number;
  slides: Slide[];
}

interface TranslatedRun {
  run_id: string;
  original_text: string;
  translated_text: string;
  source_language: string;
  target_language: string;
  model_used: string;
  adjusted_font_size: number | null;
}

export default function NewTranslatorPage() {
  const [document, setDocument] = useState<UploadedDocument | null>(null);
  const [translatedRuns, setTranslatedRuns] = useState<TranslatedRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  
  // Translation settings
  const [sourceLang, setSourceLang] = useState<'ja' | 'en'>('ja');
  const [targetLang, setTargetLang] = useState<'ja' | 'en'>('en');
  const [model, setModel] = useState<string>('auto');

  const handleFileUpload = useCallback(async (file: File) => {
    if (!file.name.endsWith('.pptx')) {
      setError('Only .pptx files are supported');
      return;
    }

    setLoading(true);
    setError(null);
    setProgress(0);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch('/api/upload-new', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Upload failed');
      }

      const data = await response.json();
      setDocument(data);
      setProgress(100);

    } catch (err) {
      console.error('Upload error:', err);
      setError(err instanceof Error ? err.message : 'Failed to upload file');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleTranslate = useCallback(async () => {
    if (!document) return;

    setTranslating(true);
    setError(null);
    setProgress(0);

    try {
      // Flatten all runs from all slides
      const allRuns: TextRun[] = [];
      for (const slide of document.slides) {
        for (const textBox of slide.text_boxes) {
          allRuns.push(...textBox.runs);
        }
      }

      const response = await fetch('/api/translate-new', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          runs: allRuns,
          source_language: sourceLang,
          target_language: targetLang,
          model: model,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Translation failed');
      }

      const data = await response.json();
      setTranslatedRuns(data.translated_runs);
      setProgress(100);

    } catch (err) {
      console.error('Translation error:', err);
      setError(err instanceof Error ? err.message : 'Failed to translate');
    } finally {
      setTranslating(false);
    }
  }, [document, sourceLang, targetLang, model]);

  const handleExport = useCallback(async () => {
    if (!document || translatedRuns.length === 0) return;

    setExporting(true);
    setError(null);

    try {
      const response = await fetch('/api/export-new', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          job_id: document.job_id,
          filename: `translated_${document.filename}`,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Export failed');
      }

      // Download the file
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = `translated_${document.filename}`;
      window.document.body.appendChild(a);
      a.click();
      window.document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

    } catch (err) {
      console.error('Export error:', err);
      setError(err instanceof Error ? err.message : 'Failed to export');
    } finally {
      setExporting(false);
    }
  }, [document, translatedRuns]);

  // Manual edit handler
  const handleTextEdit = useCallback((runId: string, newText: string) => {
    setTranslatedRuns(prev =>
      prev.map(run =>
        run.run_id === runId
          ? { ...run, translated_text: newText }
          : run
      )
    );
  }, []);

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-900 via-purple-900 to-gray-900 text-white">
      {/* Header */}
      <header className="text-center py-12">
        <h1 className="text-5xl font-bold mb-4 bg-gradient-to-r from-white to-purple-400 bg-clip-text text-transparent">
          PPTX Translator
        </h1>
        <p className="text-gray-400 text-lg">
          Preserve formatting while translating PowerPoint presentations
        </p>
      </header>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 pb-12">
        {/* Upload Section */}
        {!document && (
          <div className="bg-gray-800/50 rounded-2xl p-8 border border-purple-500/20">
            <h2 className="text-xl font-semibold mb-4">Upload PowerPoint</h2>
            <div
              className="border-2 border-dashed border-purple-500/50 rounded-xl p-12 text-center cursor-pointer hover:border-purple-400 transition-colors"
              onClick={() => {
                const input = window.document.createElement('input');
                input.type = 'file';
                input.accept = '.pptx';
                input.onchange = (e) => {
                  const file = (e.target as HTMLInputElement).files?.[0];
                  if (file) handleFileUpload(file);
                };
                input.click();
              }}
            >
              <p className="text-gray-400 mb-2">Click or drag to upload</p>
              <p className="text-sm text-gray-500">Supports .pptx files up to 50MB</p>
            </div>
            {loading && (
              <div className="mt-4">
                <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-purple-500 transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="text-center text-gray-400 mt-2">Extracting text runs...</p>
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="mt-4 p-4 bg-red-500/20 border border-red-500 rounded-xl text-red-300">
            {error}
          </div>
        )}

        {/* Document Info and Translation Settings */}
        {document && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
            {/* Document Info */}
            <div className="lg:col-span-2 bg-gray-800/50 rounded-2xl p-6 border border-purple-500/20">
              <h2 className="text-xl font-semibold mb-4">{document.filename}</h2>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div className="bg-gray-700/50 rounded-xl p-4">
                  <div className="text-3xl font-bold text-purple-400">{document.total_slides}</div>
                  <div className="text-gray-400 text-sm">Slides</div>
                </div>
                <div className="bg-gray-700/50 rounded-xl p-4">
                  <div className="text-3xl font-bold text-blue-400">{document.total_text_boxes}</div>
                  <div className="text-gray-400 text-sm">Text Boxes</div>
                </div>
                <div className="bg-gray-700/50 rounded-xl p-4">
                  <div className="text-3xl font-bold text-green-400">{document.total_runs}</div>
                  <div className="text-gray-400 text-sm">Text Runs</div>
                </div>
              </div>
            </div>

            {/* Translation Settings */}
            <div className="bg-gray-800/50 rounded-2xl p-6 border border-purple-500/20">
              <h3 className="text-lg font-semibold mb-4">Translation Settings</h3>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Source Language</label>
                  <select
                    value={sourceLang}
                    onChange={(e) => setSourceLang(e.target.value as 'ja' | 'en')}
                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                  >
                    <option value="ja">Japanese</option>
                    <option value="en">English</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm text-gray-400 mb-1">Target Language</label>
                  <select
                    value={targetLang}
                    onChange={(e) => setTargetLang(e.target.value as 'ja' | 'en')}
                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                  >
                    <option value="en">English</option>
                    <option value="ja">Japanese</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm text-gray-400 mb-1">Translation Model</label>
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                  >
                    <optgroup label="Free Tier">
                      <option value="auto">Auto (Best Available)</option>
                      <option value="gemini">Google Gemini (Free)</option>
                      <option value="qwen">Qwen (Free credits)</option>
                    </optgroup>
                    <optgroup label="OpenCode (Unified)">
                      <option value="opencode">OpenCode Auto</option>
                      <option value="opencode-glm">OpenCode GLM-4</option>
                      <option value="opencode-kimi">OpenCode Kimi K2.5</option>
                      <option value="opencode-minimax">OpenCode MiniMax M2.5</option>
                    </optgroup>
                    <optgroup label="Direct APIs">
                      <option value="kimi">Kimi/Moonshot</option>
                      <option value="glm">GLM-4</option>
                      <option value="minimax">MiniMax</option>
                    </optgroup>
                    <optgroup label="Local">
                      <option value="ollama">Ollama (Local)</option>
                    </optgroup>
                  </select>
                </div>

                <button
                  onClick={handleTranslate}
                  disabled={translating}
                  className={`w-full py-3 rounded-xl font-semibold transition-all ${
                    translating
                      ? 'bg-gray-600 cursor-not-allowed'
                      : 'bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500'
                  }`}
                >
                  {translating ? 'Translating...' : 'Translate'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Translation Progress */}
        {translating && (
          <div className="mt-4p-4 bg-blue-500/20 border border-blue-500 rounded-xl">
            <div className="flex items-center justify-between mb-2">
              <span>Translating...</span>
              <span>{progress}%</span>
            </div>
            <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Preview and Review Section */}
        {document && translatedRuns.length > 0 && (
          <div className="mt-6 bg-gray-800/50 rounded-2xl p-6 border border-purple-500/20">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">Review Translations</h2>
              <button
                onClick={handleExport}
                disabled={exporting}
                className={`px-6 py-2 rounded-xl font-semibold transition-all ${
                  exporting
                    ? 'bg-gray-600 cursor-not-allowed'
                    : 'bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-500 hover:to-emerald-500'
                }`}
              >
                {exporting ? 'Exporting...' : 'Export PPTX'}
              </button>
            </div>

            {/* Slide-by-slide review */}
            <div className="space-y-6 max-h-[600px] overflow-y-auto">
              {document.slides.map((slide, slideIdx) => (
                <div key={slide.slide_index} className="border border-gray-700 rounded-xl p-4">
                  <h3 className="text-lg font-medium text-purple-400 mb-3">
                    Slide {slideIdx + 1}
                  </h3>
                  
                  {slide.text_boxes.map((textBox, boxIdx) => (
                    <div key={textBox.box_id} className="mb-4 bg-gray-900/50 rounded-lg p-3">
                      {textBox.runs.map((run, runIdx) => {
                        const translated = translatedRuns.find(
                          t => t.run_id === run.run_id
                        );
                        
                        return (
                          <div key={run.run_id} className="mb-2">
                            <div className="flex items-start gap-4">
                              <div className="flex-1">
                                <div className="text-sm text-gray-400 mb-1">
                                  Original:
                                </div>
                                <div className="bg-gray-800 rounded px-3 py-2 font-mono text-sm">
                                  {run.text}
                                </div>
                              </div>
                              <div className="flex-1">
                                <div className="text-sm text-gray-400 mb-1 flex items-center justify-between">
                                  <span>Translation:</span>
                                  <span className="text-xs text-purple-400">
                                    {translated?.model_used}
                                  </span>
                                </div>
                                <input
                                  type="text"
                                  value={translated?.translated_text || ''}
                                  onChange={(e) => handleTextEdit(run.run_id, e.target.value)}
                                  className="w-full bg-gray-800 rounded px-3 py-2 font-mono text-sm border border-gray-700 focus:border-purple-500 focus:outline-none"
                                />
                                {translated?.adjusted_font_size && (
                                  <div className="text-xs text-yellow-400 mt-1">
                                    Font adjusted to {translated.adjusted_font_size.toFixed(1)}pt
                                  </div>
                                )}
                              </div>
                            </div>
                            
                            {/* Style info */}
                            <div className="flex gap-2 mt-1 text-xs text-gray-500">
                              {run.style?.bold && <span className="px-1 bg-gray-700 rounded">Bold</span>}
                              {run.style?.italic && <span className="px-1 bg-gray-700 rounded">Italic</span>}
                              {run.style?.font_size && <span className="px-1 bg-gray-700 rounded">{run.style.font_size}pt</span>}
                              {run.style?.font_name && <span className="px-1 bg-gray-700 rounded">{run.style.font_name}</span>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}