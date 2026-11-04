import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ cacheLife: () => {}, cacheTag: () => {} }));

type Reply = { status: number; json: unknown };

/** openapi-fetch captures global fetch when the client is created, so the module is imported after stubbing. */
async function serverWith(reply: Reply) {
  vi.resetModules();
  vi.stubGlobal(
    "fetch",
    async () =>
      new Response(JSON.stringify(reply.json), {
        status: reply.status,
        headers: { "content-type": "application/json" },
      }),
  );
  return import("./server");
}

const SERVER_ERROR: Reply = { status: 503, json: { detail: "unavailable" } };

describe("catalog fetchers", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.unstubAllGlobals());

  // These run inside "use cache": a returned fallback would be served as an empty shop until it expires.
  it("getCategories rejects on a server error instead of returning an empty list", async () => {
    const { getCategories } = await serverWith(SERVER_ERROR);
    await expect(getCategories()).rejects.toThrow(/503/);
  });

  it("getProducts rejects on a server error instead of returning no results", async () => {
    const { getProducts } = await serverWith(SERVER_ERROR);
    await expect(getProducts({})).rejects.toThrow(/503/);
  });

  it("getProduct rejects on a server error instead of reporting not found", async () => {
    const { getProduct } = await serverWith(SERVER_ERROR);
    await expect(getProduct("red-sneakers")).rejects.toThrow(/503/);
  });

  it("getDeliveryRegions rejects on a server error instead of returning no regions", async () => {
    const { getDeliveryRegions } = await serverWith(SERVER_ERROR);
    await expect(getDeliveryRegions()).rejects.toThrow(/503/);
  });

  it("getProduct returns null for a product that does not exist", async () => {
    const { getProduct } = await serverWith({ status: 404, json: { detail: "Not found." } });
    await expect(getProduct("missing")).resolves.toBeNull();
  });

  it("getProducts returns the page on success", async () => {
    const page = { count: 1, next: null, previous: null, results: [{ id: 7, slug: "red-sneakers" }] };
    const { getProducts } = await serverWith({ status: 200, json: page });
    await expect(getProducts({})).resolves.toEqual(page);
  });

  it("getCategories keeps active categories only", async () => {
    const { getCategories } = await serverWith({
      status: 200,
      json: {
        count: 2,
        next: null,
        previous: null,
        results: [
          { id: 1, slug: "shoes", is_active: true },
          { id: 2, slug: "hidden", is_active: false },
        ],
      },
    });
    await expect(getCategories()).resolves.toEqual([{ id: 1, slug: "shoes", is_active: true }]);
  });
});
