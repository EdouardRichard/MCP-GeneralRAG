/**
 * Locale resource layer (011 T031, FR-027).
 *
 * Zero-dependency i18n (research R10): LocaleProvider (React Context) +
 * useLocale() hook + t(key) lookup + localStorage persistence (key
 * rag-mcp.locale). Default English (zero break for existing users).
 *
 * Fallback semantics (contract §4, deterministic): a missing key falls back
 * to the English value; if both lack the key the key string itself is
 * rendered — never an empty string, never a crash.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { en } from './en';
import { zh } from './zh';
import type { LocaleDict, LocaleKey } from './en';

export type Locale = 'zh' | 'en';

const STORAGE_KEY = 'rag-mcp.locale';

const DICTS: Record<Locale, LocaleDict> = { en, zh };

function readStoredLocale(): Locale {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'zh' || raw === 'en') return raw;
  } catch {
    // localStorage unavailable (private mode etc.) — fall back to English.
  }
  return 'en';
}

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: LocaleKey) => string;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      // Persistence is best-effort; never block rendering.
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
  }, []);

  const t = useCallback(
    (key: LocaleKey): string => {
      const dict = DICTS[locale] as Partial<Record<LocaleKey, string>>;
      return dict[key] ?? en[key] ?? key;
    },
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (ctx === null) {
    // Used outside a provider: deterministic English fallback, never a crash.
    return {
      locale: 'en',
      setLocale: () => undefined,
      t: (key) => en[key] ?? key,
    };
  }
  return ctx;
}

export { en, zh };
export type { LocaleKey, LocaleDict };