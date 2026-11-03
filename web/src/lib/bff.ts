/**
 * Backend-for-frontend core: forwards browser calls to Django while keeping JWTs and the guest
 * cart token in httpOnly cookies (research R2, contracts/web-routes.md). Pure apart from the
 * injected `fetch`, so it is unit-tested without Next.js.
 */

export type Jar = { access?: string; refresh?: string; cart?: string };
export type CookieChange = { name: keyof Jar; value: string | null };
export interface Upstream {
  apiUrl: string;
  fetch: typeof fetch;
}
export interface ForwardInput {
  method: string;
  path: string;
  search?: string;
  headers?: HeadersInit;
  body?: ArrayBuffer | null;
  jar: Jar;
}
export interface ForwardResult {
  status: number;
  headers: Headers;
  body: ArrayBuffer | null;
  cookies: CookieChange[];
}
export interface JsonResult {
  status: number;
  body: unknown;
  cookies: CookieChange[];
}

/** Request headers the browser may send through; everything else (cookie, authorization…) is dropped. */
const PASS_REQUEST = ["content-type", "accept", "accept-language"];
/** Response headers passed back; set-cookie and hop-by-hop headers are dropped. */
const PASS_RESPONSE = ["content-type", "content-disposition", "cache-control", "x-request-id"];
const BLOCKED = /^auth\/(login|refresh|register)(\/|$)/;
const SAFE_PATH = /^[A-Za-z0-9_\-.~/]*$/;

export function isAllowedPath(path: string): boolean {
  if (!SAFE_PATH.test(path) || BLOCKED.test(path)) return false;
  return !path.split("/").some((seg, i, all) => seg === ".." || seg === "." || (seg === "" && i > 0 && i < all.length - 1));
}

function jsonBody(o: unknown): ArrayBuffer {
  return new TextEncoder().encode(JSON.stringify(o)).buffer as ArrayBuffer;
}

function parseJson(buf: ArrayBuffer | null, headers: Headers): unknown {
  if (!buf || !headers.get("content-type")?.includes("json")) return undefined;
  try {
    return JSON.parse(new TextDecoder().decode(buf));
  } catch {
    return undefined;
  }
}

function notFound(): ForwardResult {
  return {
    status: 404,
    headers: new Headers({ "content-type": "application/json" }),
    body: jsonBody({ detail: "Not found." }),
    cookies: [],
  };
}

async function call(
  up: Upstream,
  method: string,
  path: string,
  opts: { search?: string; headers?: HeadersInit; body?: ArrayBuffer | null; access?: string; cart?: string },
) {
  const headers = new Headers();
  const incoming = new Headers(opts.headers);
  for (const name of PASS_REQUEST) {
    const v = incoming.get(name);
    if (v) headers.set(name, v);
  }
  if (opts.access) headers.set("authorization", `Bearer ${opts.access}`);
  if (opts.cart) headers.set("x-cart-token", opts.cart);
  const hasBody = opts.body != null && !["GET", "HEAD"].includes(method);
  const res = await up.fetch(`${up.apiUrl}/api/${path}${opts.search ?? ""}`, {
    method,
    headers,
    body: hasBody ? opts.body : undefined,
    cache: "no-store",
    redirect: "manual",
  });
  const body = res.status === 204 || method === "HEAD" ? null : await res.arrayBuffer();
  return { status: res.status, headers: res.headers, body: body && body.byteLength ? body : null };
}

async function refreshTokens(up: Upstream, refresh: string) {
  const res = await call(up, "POST", "auth/refresh/", {
    headers: { "content-type": "application/json" },
    body: jsonBody({ refresh }),
  });
  if (res.status !== 200) return null;
  const data = parseJson(res.body, res.headers) as { access?: string; refresh?: string } | undefined;
  return data?.access ? { access: data.access, refresh: data.refresh } : null;
}

export async function forward(input: ForwardInput, up: Upstream): Promise<ForwardResult> {
  const path = input.path.replace(/^\/+/, "");
  if (!isAllowedPath(path)) return notFound();
  const method = input.method.toUpperCase();
  const cookies: CookieChange[] = [];
  let access = input.jar.access;

  const send = (token: string | undefined) =>
    call(up, method, path, { search: input.search, headers: input.headers, body: input.body, access: token, cart: input.jar.cart });

  let res = await send(access);

  if (res.status === 401 && access) {
    const fresh = input.jar.refresh ? await refreshTokens(up, input.jar.refresh) : null;
    if (fresh) {
      access = fresh.access;
      cookies.push({ name: "access", value: fresh.access });
      if (fresh.refresh) cookies.push({ name: "refresh", value: fresh.refresh });
    } else {
      // Dead session: forget it and let public endpoints (cart, catalog) work anonymously.
      access = undefined;
      cookies.push({ name: "access", value: null }, { name: "refresh", value: null });
    }
    res = await send(access);
  }

  let body = res.body;
  const data = res.status < 300 ? parseJson(res.body, res.headers) : undefined;
  if (data && typeof data === "object" && !Array.isArray(data) && "token" in data) {
    // Cart responses carry the guest cart secret: keep it in the httpOnly cookie, never in the page.
    const { token, ...rest } = data as { token?: unknown };
    if (!access && typeof token === "string" && token && token !== input.jar.cart) {
      cookies.push({ name: "cart", value: token });
    }
    body = jsonBody(rest);
  }

  const headers = new Headers();
  for (const name of PASS_RESPONSE) {
    const v = res.headers.get(name);
    if (v) headers.set(name, v);
  }
  return { status: res.status, headers, body, cookies };
}

const JSON_HEADERS = { "content-type": "application/json" };

async function fetchMe(up: Upstream, access: string) {
  const me = await call(up, "GET", "auth/me/", { access });
  return me.status === 200 ? parseJson(me.body, me.headers) : null;
}

export async function login(
  creds: { username: string; password: string },
  jar: Jar,
  up: Upstream,
): Promise<JsonResult> {
  const res = await call(up, "POST", "auth/login/", {
    headers: JSON_HEADERS,
    body: jsonBody({ username: creds.username, password: creds.password }),
  });
  if (res.status !== 200) {
    if (res.status === 400) return { status: 400, body: parseJson(res.body, res.headers) ?? {}, cookies: [] };
    return {
      status: 401,
      body: { detail: "Invalid username or password.", code: "invalid_credentials" },
      cookies: [],
    };
  }
  const tokens = parseJson(res.body, res.headers) as { access: string; refresh: string };
  const cookies: CookieChange[] = [
    { name: "access", value: tokens.access },
    { name: "refresh", value: tokens.refresh },
  ];
  if (jar.cart) {
    // A failed merge must not block login; the guest cart simply stays behind.
    await call(up, "POST", "cart/merge/", {
      headers: JSON_HEADERS,
      body: jsonBody({ cart_token: jar.cart }),
      access: tokens.access,
    }).catch(() => undefined);
    cookies.push({ name: "cart", value: null });
  }
  return { status: 200, body: { user: await fetchMe(up, tokens.access) }, cookies };
}

export async function register(
  data: Record<string, unknown> & { username: string; password: string },
  jar: Jar,
  up: Upstream,
): Promise<JsonResult> {
  const res = await call(up, "POST", "auth/register/", { headers: JSON_HEADERS, body: jsonBody(data) });
  if (res.status !== 201) {
    return { status: res.status === 400 ? 400 : res.status, body: parseJson(res.body, res.headers) ?? {}, cookies: [] };
  }
  const session = await login({ username: data.username, password: data.password }, jar, up);
  return session.status === 200 ? { ...session, status: 201 } : session;
}

export async function currentUser(jar: Jar, up: Upstream): Promise<JsonResult> {
  if (!jar.access && !jar.refresh) return { status: 200, body: { user: null }, cookies: [] };
  // With only a refresh cookie, send a placeholder so the 401 path refreshes it.
  const res = await forward({ method: "GET", path: "auth/me/", jar: { ...jar, access: jar.access ?? "expired" } }, up);
  const user = res.status === 200 ? parseJson(res.body, res.headers) ?? null : null;
  return { status: 200, body: { user }, cookies: res.cookies };
}
