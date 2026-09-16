'use client';

import { useState, FormEvent } from 'react';
import ThemeToggle from '@/components/ThemeToggle';
import { APP_VERSION } from '@/lib/version';

const dict = {
  en: {
    heading: 'Sign in',
    hint: 'Enter the access passphrase',
    placeholder: 'Passphrase',
    button: 'Continue',
    checking: 'Checking…',
    error: 'Incorrect passphrase',
  },
  ja: {
    heading: 'サインイン',
    hint: 'アクセスパスフレーズを入力してください',
    placeholder: 'パスフレーズ',
    button: '続ける',
    checking: '確認中…',
    error: 'パスフレーズが正しくありません',
  },
} as const;

type Lang = keyof typeof dict;

export default function LoginPage() {
  const [lang, setLang] = useState<Lang>('en');
  const t = dict[lang];
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim() || busy) return;
    setBusy(true);
    setError(false);
    try {
      const res = await fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ passphrase: value }),
      });
      if (res.ok) {
        const params = new URLSearchParams(window.location.search);
        const raw = params.get('next') || '/';
        // Only allow same-origin relative paths (no '//', backslash, or control chars).
        const next =
          /^\/(?!\/)/.test(raw) && !raw.includes('\\') && !/[\u0000-\u001f\u007f]/.test(raw)
            ? raw
            : '/';
        window.location.href = next;
      } else {
        setError(true);
      }
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950 flex flex-col">
      <header className="bg-white dark:bg-zinc-950 border-b border-gray-200 dark:border-zinc-800">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700 dark:text-zinc-200 select-none">PPTX Translator</span>
          <div className="flex items-center gap-3">
            <div className="flex items-center bg-gray-100 dark:bg-zinc-800 rounded-lg p-0.5">
              {(Object.keys(dict) as Lang[]).map((l) => (
                <button
                  key={l}
                  onClick={() => setLang(l)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                    lang === l ? 'bg-white dark:bg-zinc-700 text-gray-700 dark:text-zinc-100 shadow-sm' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-700 dark:hover:text-zinc-200'
                  }`}
                >
                  {l === 'en' ? 'EN' : 'JP'}
                </button>
              ))}
            </div>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-6">
        <form onSubmit={onSubmit} className="w-full max-w-sm bg-gray-50/50 dark:bg-zinc-900/60 border border-gray-200 dark:border-zinc-800 rounded-xl p-6">
          <h1 className="text-lg text-gray-800 dark:text-zinc-100 mb-1">{t.heading}</h1>
          <p className="text-xs text-gray-500 dark:text-zinc-400 mb-5">{t.hint}</p>
          <input
            type="password"
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={t.placeholder}
            className={`w-full rounded-lg px-3 py-2.5 text-sm border transition-colors focus:outline-none focus:ring-1 bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 placeholder:text-gray-400 dark:placeholder:text-zinc-500 ${
              error
                ? 'border-red-300 dark:border-red-800 focus:border-red-400 focus:ring-red-400'
                : 'border-gray-300 dark:border-zinc-700 focus:border-blue-500 focus:ring-blue-500'
            }`}
          />
          {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{t.error}</p>}
          <button
            type="submit"
            disabled={busy || !value.trim()}
            className="mt-4 w-full py-2.5 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 dark:disabled:bg-zinc-700 disabled:text-gray-500 dark:disabled:text-zinc-500 transition-colors shadow-sm"
          >
            {busy ? t.checking : t.button}
          </button>
        </form>
      </main>

      <footer className="border-t border-gray-100 dark:border-zinc-800 py-4 mt-auto">
        <div className="max-w-5xl mx-auto px-6 text-xs text-gray-400 dark:text-zinc-500">
          <span>PPTX Translator</span>
          {APP_VERSION && (
            <span className="ml-2 text-gray-300 dark:text-zinc-600">{APP_VERSION}</span>
          )}
        </div>
      </footer>
    </div>
  );
}
