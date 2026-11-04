import { describe, expect, it } from "vitest";
import { ApiError, toApiError } from "./errors";

describe("toApiError", () => {
  it("reads {detail, code}", () => {
    const e = toApiError(400, { detail: "Only 2 left.", code: "out_of_stock" });
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 400, code: "out_of_stock", detail: "Only 2 left." });
    expect(e.message).toBe("Only 2 left.");
  });
  it("reads DRF field errors", () => {
    const e = toApiError(400, { contact_phone: ["Enter a valid phone."], street: "This field is required." });
    expect(e.fields).toEqual({ contact_phone: ["Enter a valid phone."], street: ["This field is required."] });
    expect(e.detail).toBe("Enter a valid phone.");
  });
  it("uses non_field_errors as the detail", () => {
    const e = toApiError(400, { non_field_errors: ["Cart is empty."] });
    expect(e.detail).toBe("Cart is empty.");
    expect(e.fields).toBeUndefined();
  });
  it("flattens nested errors to strings", () => {
    const e = toApiError(400, { items: [{ quantity: ["Too many."] }] });
    expect(e.fields).toEqual({ items: ["Too many."] });
  });
  it("falls back to a generic message", () => {
    expect(toApiError(502, "<html>").detail).toBe("Something went wrong. Please try again.");
    expect(toApiError(500, null).status).toBe(500);
  });
});
