import { describe, expect, it } from "vitest";
import { currentUser, forward, login, register, type Upstream } from "./bff";

type Call = { url: string; method: string; headers: Headers; body: string | null };
type Reply = { status: number; json?: unknown; headers?: Record<string, string> };

function fakeUpstream(handler: (call: Call, n: number) => Reply) {
  const calls: Call[] = [];
  const upstream: Upstream = {
    apiUrl: "http://django:8000",
    fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
      const body = init?.body == null ? null : new TextDecoder().decode(init.body as ArrayBuffer);
      const call = { url: String(input), method: init?.method ?? "GET", headers: new Headers(init?.headers), body };
      calls.push(call);
      const r = handler(call, calls.length);
      const headers = new Headers({ "content-type": "application/json", ...(r.headers ?? {}) });
      return new Response(r.json === undefined ? null : JSON.stringify(r.json), { status: r.status, headers });
    }) as typeof fetch,
  };
  return { upstream, calls };
}

const enc = (o: unknown) => new TextEncoder().encode(JSON.stringify(o)).buffer as ArrayBuffer;
const text = (b: ArrayBuffer | null) => (b ? new TextDecoder().decode(b) : "");

describe("forward", () => {
  it("forwards method, path, query, body and content type", async () => {
    const { upstream, calls } = fakeUpstream(() => ({ status: 200, json: { ok: 1 } }));
    const res = await forward(
      {
        method: "POST",
        path: "cart/items/",
        search: "?x=1",
        headers: { "content-type": "application/json", cookie: "sa_access=leak", authorization: "Bearer evil" },
        body: enc({ product_id: 3 }),
        jar: {},
      },
      upstream,
    );
    expect(calls[0].url).toBe("http://django:8000/api/cart/items/?x=1");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toBe('{"product_id":3}');
    expect(calls[0].headers.get("content-type")).toBe("application/json");
    expect(calls[0].headers.get("cookie")).toBeNull();
    expect(calls[0].headers.get("authorization")).toBeNull();
    expect(res.status).toBe(200);
    expect(JSON.parse(text(res.body))).toEqual({ ok: 1 });
  });

  it("passes multipart content type with its boundary", async () => {
    const { upstream, calls } = fakeUpstream(() => ({ status: 201, json: {} }));
    await forward(
      {
        method: "POST",
        path: "products/",
        headers: { "content-type": "multipart/form-data; boundary=abc" },
        body: new TextEncoder().encode("--abc--").buffer as ArrayBuffer,
        jar: { access: "A" },
      },
      upstream,
    );
    expect(calls[0].headers.get("content-type")).toBe("multipart/form-data; boundary=abc");
  });

  it("adds bearer and cart token from cookies", async () => {
    const { upstream, calls } = fakeUpstream(() => ({ status: 200, json: {} }));
    await forward({ method: "GET", path: "cart/", jar: { access: "A", cart: "C" } }, upstream);
    expect(calls[0].headers.get("authorization")).toBe("Bearer A");
    expect(calls[0].headers.get("x-cart-token")).toBe("C");
  });

  it("refreshes once on 401, retries, and stores rotated tokens", async () => {
    const { upstream, calls } = fakeUpstream((call) => {
      if (call.url.endsWith("/api/auth/refresh/")) return { status: 200, json: { access: "A2", refresh: "R2" } };
      return call.headers.get("authorization") === "Bearer A2" ? { status: 200, json: { id: 1 } } : { status: 401, json: {} };
    });
    const res = await forward({ method: "GET", path: "orders/", jar: { access: "A1", refresh: "R1" } }, upstream);
    expect(calls.map((c) => c.url.replace("http://django:8000/api/", ""))).toEqual(["orders/", "auth/refresh/", "orders/"]);
    expect(JSON.parse(calls[1].body!)).toEqual({ refresh: "R1" });
    expect(res.status).toBe(200);
    expect(res.cookies).toEqual(
      expect.arrayContaining([
        { name: "access", value: "A2" },
        { name: "refresh", value: "R2" },
      ]),
    );
  });

  it("keeps the refresh cookie when the refresh response does not rotate it", async () => {
    const { upstream } = fakeUpstream((call) => {
      if (call.url.endsWith("/auth/refresh/")) return { status: 200, json: { access: "A2" } };
      return call.headers.get("authorization") === "Bearer A2" ? { status: 200, json: {} } : { status: 401 };
    });
    const res = await forward({ method: "GET", path: "orders/", jar: { access: "A1", refresh: "R1" } }, upstream);
    expect(res.cookies).toEqual([{ name: "access", value: "A2" }]);
  });

  it("on failed refresh clears auth cookies and retries anonymously", async () => {
    const { upstream, calls } = fakeUpstream((call) => {
      if (call.url.endsWith("/auth/refresh/")) return { status: 401, json: { detail: "expired" } };
      return call.headers.get("authorization") ? { status: 401, json: {} } : { status: 200, json: { token: "C9", items: [] } };
    });
    const res = await forward({ method: "GET", path: "cart/", jar: { access: "A1", refresh: "R1" } }, upstream);
    expect(calls).toHaveLength(3);
    expect(calls[2].headers.get("authorization")).toBeNull();
    expect(res.status).toBe(200);
    expect(res.cookies).toEqual(
      expect.arrayContaining([
        { name: "access", value: null },
        { name: "refresh", value: null },
        { name: "cart", value: "C9" },
      ]),
    );
  });

  it("returns the 401 when an anonymous retry is also refused", async () => {
    const { upstream } = fakeUpstream((call) =>
      call.url.endsWith("/auth/refresh/") ? { status: 401 } : { status: 401, json: { detail: "Login required." } },
    );
    const res = await forward({ method: "GET", path: "orders/", jar: { access: "A1", refresh: "R1" } }, upstream);
    expect(res.status).toBe(401);
  });

  it("does not retry when no auth was sent", async () => {
    const { upstream, calls } = fakeUpstream(() => ({ status: 401, json: {} }));
    const res = await forward({ method: "GET", path: "orders/", jar: {} }, upstream);
    expect(calls).toHaveLength(1);
    expect(res.status).toBe(401);
  });

  it("stores a new guest cart token but not for logged-in users", async () => {
    const { upstream } = fakeUpstream(() => ({ status: 200, json: { token: "NEW", items: [] } }));
    const anon = await forward({ method: "GET", path: "cart/", jar: { cart: "OLD" } }, upstream);
    expect(anon.cookies).toEqual([{ name: "cart", value: "NEW" }]);
    const same = await forward({ method: "GET", path: "cart/", jar: { cart: "NEW" } }, upstream);
    expect(same.cookies).toEqual([]);
    const user = await forward({ method: "GET", path: "cart/", jar: { access: "A" } }, upstream);
    expect(user.cookies).toEqual([]);
  });

  it("removes the cart token from the body so page scripts never see it", async () => {
    const { upstream } = fakeUpstream(() => ({ status: 200, json: { token: "SECRET", items: [], subtotal: "0.00" } }));
    const anon = await forward({ method: "GET", path: "cart/", jar: {} }, upstream);
    expect(JSON.parse(text(anon.body))).toEqual({ items: [], subtotal: "0.00" });
    const user = await forward({ method: "GET", path: "cart/", jar: { access: "A" } }, upstream);
    expect(JSON.parse(text(user.body))).toEqual({ items: [], subtotal: "0.00" });
  });

  it("drops set-cookie and hop-by-hop headers", async () => {
    const { upstream } = fakeUpstream(() => ({
      status: 200,
      json: {},
      headers: { "set-cookie": "sessionid=x", connection: "keep-alive", "x-request-id": "r1" },
    }));
    const res = await forward({ method: "GET", path: "products/", jar: {} }, upstream);
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("connection")).toBeNull();
    expect(res.headers.get("content-type")).toBe("application/json");
  });

  it.each(["auth/login/", "auth/refresh/", "auth/register/", "auth/login", "../secret/", "cart//x", "a\\b"])(
    "refuses %s",
    async (path) => {
      const { upstream, calls } = fakeUpstream(() => ({ status: 200, json: {} }));
      const res = await forward({ method: "POST", path, jar: {} }, upstream);
      expect(res.status).toBe(404);
      expect(calls).toHaveLength(0);
    },
  );
});

describe("login", () => {
  it("sets tokens, merges the guest cart and clears the cart cookie", async () => {
    const { upstream, calls } = fakeUpstream((call) => {
      if (call.url.endsWith("/auth/login/")) return { status: 200, json: { access: "A", refresh: "R" } };
      if (call.url.endsWith("/cart/merge/")) return { status: 200, json: {} };
      if (call.url.endsWith("/auth/me/")) return { status: 200, json: { id: 1, username: "amina", role: "customer" } };
      return { status: 500 };
    });
    const res = await login({ username: "amina", password: "pw" }, { cart: "G1" }, upstream);
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ user: { id: 1, username: "amina", role: "customer" } });
    const merge = calls.find((c) => c.url.endsWith("/cart/merge/"))!;
    expect(merge.headers.get("authorization")).toBe("Bearer A");
    expect(JSON.parse(merge.body!)).toEqual({ cart_token: "G1" });
    expect(res.cookies).toEqual(
      expect.arrayContaining([
        { name: "access", value: "A" },
        { name: "refresh", value: "R" },
        { name: "cart", value: null },
      ]),
    );
  });

  it("still logs in when the merge fails", async () => {
    const { upstream } = fakeUpstream((call) => {
      if (call.url.endsWith("/auth/login/")) return { status: 200, json: { access: "A", refresh: "R" } };
      if (call.url.endsWith("/cart/merge/")) return { status: 400, json: { detail: "bad" } };
      return { status: 200, json: { id: 1, role: "customer" } };
    });
    const res = await login({ username: "u", password: "p" }, { cart: "G1" }, upstream);
    expect(res.status).toBe(200);
  });

  it("skips the merge without a guest cart", async () => {
    const { upstream, calls } = fakeUpstream((call) =>
      call.url.endsWith("/auth/login/") ? { status: 200, json: { access: "A", refresh: "R" } } : { status: 200, json: { id: 1 } },
    );
    await login({ username: "u", password: "p" }, {}, upstream);
    expect(calls.some((c) => c.url.endsWith("/cart/merge/"))).toBe(false);
  });

  it("gives one generic message for bad credentials", async () => {
    const { upstream } = fakeUpstream(() => ({ status: 401, json: { detail: "No active account found with the given credentials" } }));
    const res = await login({ username: "u", password: "bad" }, {}, upstream);
    expect(res.status).toBe(401);
    expect(res.body).toEqual({ detail: "Invalid username or password.", code: "invalid_credentials" });
    expect(res.cookies).toEqual([]);
  });
});

describe("register", () => {
  it("creates the user then logs in", async () => {
    const { upstream, calls } = fakeUpstream((call) => {
      if (call.url.endsWith("/auth/register/")) return { status: 201, json: { username: "neema" } };
      if (call.url.endsWith("/auth/login/")) return { status: 200, json: { access: "A", refresh: "R" } };
      return { status: 200, json: { id: 2, username: "neema" } };
    });
    const res = await register({ username: "neema", password: "longpass1", email: "n@x.tz" }, {}, upstream);
    expect(res.status).toBe(201);
    expect(JSON.parse(calls[1].body!)).toEqual({ username: "neema", password: "longpass1" });
    expect(res.body).toEqual({ user: { id: 2, username: "neema" } });
  });

  it("passes field errors through", async () => {
    const { upstream } = fakeUpstream(() => ({ status: 400, json: { username: ["Taken."] } }));
    const res = await register({ username: "x", password: "longpass1" }, {}, upstream);
    expect(res.status).toBe(400);
    expect(res.body).toEqual({ username: ["Taken."] });
  });
});

describe("currentUser", () => {
  it("returns null without a session and does not call upstream", async () => {
    const { upstream, calls } = fakeUpstream(() => ({ status: 200, json: {} }));
    expect((await currentUser({}, upstream)).body).toEqual({ user: null });
    expect(calls).toHaveLength(0);
  });
  it("returns the user, refreshing when needed", async () => {
    const { upstream } = fakeUpstream((call) => {
      if (call.url.endsWith("/auth/refresh/")) return { status: 200, json: { access: "A2" } };
      return call.headers.get("authorization") === "Bearer A2" ? { status: 200, json: { id: 3 } } : { status: 401 };
    });
    const res = await currentUser({ access: "A1", refresh: "R" }, upstream);
    expect(res.body).toEqual({ user: { id: 3 } });
    expect(res.cookies).toEqual([{ name: "access", value: "A2" }]);
  });
  it("returns null when the session is dead", async () => {
    const { upstream } = fakeUpstream(() => ({ status: 401 }));
    const res = await currentUser({ access: "A1", refresh: "R" }, upstream);
    expect(res.body).toEqual({ user: null });
  });
});
