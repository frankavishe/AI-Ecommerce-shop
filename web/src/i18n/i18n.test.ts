import { describe, expect, it } from "vitest";
import { en } from "./en";
import { sw } from "./sw";

function leaves(obj: object, prefix = ""): Record<string, unknown> {
  return Object.entries(obj).reduce<Record<string, unknown>>((acc, [k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object") Object.assign(acc, leaves(v, key));
    else acc[key] = v;
    return acc;
  }, {});
}

describe("dictionaries", () => {
  const e = leaves(en);
  const s = leaves(sw);
  it("have the same keys", () => {
    expect(Object.keys(s).sort()).toEqual(Object.keys(e).sort());
  });
  it("have no empty strings", () => {
    for (const [k, v] of [...Object.entries(e), ...Object.entries(s)]) {
      expect(typeof v === "string" && v.trim().length > 0, k).toBe(true);
    }
  });
});

import { fmt, localized, pickLocale } from "./config";

describe("pickLocale", () => {
  it("prefers the cookie", () => {
    expect(pickLocale("sw", "en-US")).toBe("sw");
    expect(pickLocale("en", "sw-TZ")).toBe("en");
  });
  it("falls back to Accept-Language, then English", () => {
    expect(pickLocale(undefined, "sw-TZ,sw;q=0.9,en;q=0.8")).toBe("sw");
    expect(pickLocale(undefined, "en;q=0.9,sw;q=0.5")).toBe("en");
    expect(pickLocale("fr", "fr-FR")).toBe("en");
    expect(pickLocale(undefined, null)).toBe("en");
  });
});

describe("fmt and localized", () => {
  it("fills placeholders and leaves unknown ones", () => {
    expect(fmt("Page {page} of {pages}", { page: 1, pages: 3 })).toBe("Page 1 of 3");
    expect(fmt("Hi {name}")).toBe("Hi {name}");
  });
  it("uses Swahili content only when present", () => {
    expect(localized("sw", "Shoes", "Viatu")).toBe("Viatu");
    expect(localized("sw", "Shoes", " ")).toBe("Shoes");
    expect(localized("en", "Shoes", "Viatu")).toBe("Shoes");
  });
});
