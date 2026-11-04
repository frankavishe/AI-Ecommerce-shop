"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";
import { dictionaries, type Dictionary, type Locale } from "./config";

const I18nContext = createContext<{ locale: Locale; t: Dictionary }>({ locale: "en", t: dictionaries.en });

export function I18nProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  return <I18nContext.Provider value={{ locale, t: dictionaries[locale] }}>{children}</I18nContext.Provider>;
}

export function useT() {
  return useContext(I18nContext);
}
