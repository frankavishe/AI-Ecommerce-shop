import { describe, expect, it } from "vitest";
import { decodeSession, isExpired } from "./auth";

function jwt(payload: object) {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(payload)}.sig`;
}

describe("decodeSession", () => {
  it("reads role and user id", () => {
    expect(decodeSession(jwt({ role: "admin", user_id: 7, exp: 2000 }))).toEqual({
      role: "admin",
      userId: 7,
      exp: 2000,
    });
  });
  it("accepts string user ids", () => {
    expect(decodeSession(jwt({ role: "customer", user_id: "12", exp: 1 }))?.userId).toBe(12);
  });
  it("returns null for malformed tokens or unknown roles", () => {
    expect(decodeSession(undefined)).toBeNull();
    expect(decodeSession("not-a-jwt")).toBeNull();
    expect(decodeSession("a.!!!.c")).toBeNull();
    expect(decodeSession(jwt({ role: "superuser", user_id: 1 }))).toBeNull();
  });
});

describe("isExpired", () => {
  const now = 1_000_000;
  it("is expired within the 30 s skew", () => {
    expect(isExpired(jwt({ role: "customer", user_id: 1, exp: now + 20 }), now * 1000)).toBe(true);
    expect(isExpired(jwt({ role: "customer", user_id: 1, exp: now + 60 }), now * 1000)).toBe(false);
  });
  it("treats undecodable tokens as expired", () => {
    expect(isExpired("garbage", now * 1000)).toBe(true);
  });
});
