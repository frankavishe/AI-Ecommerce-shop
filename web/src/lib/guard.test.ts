import { describe, expect, it } from "vitest";
import { guard } from "./guard";

const now = Math.floor(Date.now() / 1000);
function jwt(payload: object) {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256" })}.${b64(payload)}.sig`;
}
const admin = jwt({ role: "admin", user_id: 1, exp: now + 600 });
const customer = jwt({ role: "customer", user_id: 2, exp: now + 600 });
const rider = jwt({ role: "rider", user_id: 3, exp: now + 600 });
const expiredAdmin = jwt({ role: "admin", user_id: 1, exp: now - 600 });

describe("guard", () => {
  it("ignores public pages", () => {
    expect(guard("/products", "", undefined)).toEqual({ action: "next" });
    expect(guard("/administrator", "", undefined)).toEqual({ action: "next" });
  });

  it("sends anonymous users to login with next", () => {
    expect(guard("/admin/orders", "?status=paid", undefined)).toEqual({
      action: "redirect",
      to: "/login?next=%2Fadmin%2Forders%3Fstatus%3Dpaid",
    });
    expect(guard("/account", "", undefined)).toEqual({ action: "redirect", to: "/login?next=%2Faccount" });
  });

  it("lets admins into admin and account", () => {
    expect(guard("/admin", "", admin)).toEqual({ action: "next" });
    expect(guard("/account/orders", "", admin)).toEqual({ action: "next" });
  });

  it("sends customers and riders away from admin", () => {
    expect(guard("/admin", "", customer)).toEqual({ action: "redirect", to: "/forbidden" });
    expect(guard("/admin/products/new", "", rider)).toEqual({ action: "redirect", to: "/forbidden" });
    expect(guard("/account", "", customer)).toEqual({ action: "next" });
  });

  it("lets an expired session through when it can refresh, keeping the role check", () => {
    expect(guard("/account", "", undefined, "R")).toEqual({ action: "next" });
    expect(guard("/admin", "", expiredAdmin, "R")).toEqual({ action: "next" });
    expect(guard("/admin", "", undefined, "R")).toEqual({ action: "redirect", to: "/login?next=%2Fadmin" });
  });

  it("treats forged/garbage tokens as anonymous", () => {
    expect(guard("/admin", "", "garbage")).toEqual({ action: "redirect", to: "/login?next=%2Fadmin" });
  });
});
