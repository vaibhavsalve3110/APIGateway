import { describe, expect, it } from "vitest";

import { toApiError } from "./api";
import { formatRemaining, secondsUntil, titleCase } from "./format";

describe("formatRemaining", () => {
  it("shows the overlap window as mm:ss", () => {
    expect(formatRemaining(1200)).toBe("20:00");
    expect(formatRemaining(1199)).toBe("19:59");
    expect(formatRemaining(5)).toBe("00:05");
  });

  it("reports an elapsed window as expired", () => {
    expect(formatRemaining(0)).toBe("expired");
    expect(formatRemaining(-3)).toBe("expired");
  });
});

describe("secondsUntil", () => {
  it("counts down to an instant and never goes negative", () => {
    const now = Date.parse("2026-09-14T08:00:00Z");
    expect(secondsUntil("2026-09-14T08:20:00Z", now)).toBe(1200);
    expect(secondsUntil("2026-09-14T07:59:00Z", now)).toBe(0);
    expect(secondsUntil(null, now)).toBe(0);
  });
});

describe("titleCase", () => {
  it("turns enum values into labels", () => {
    expect(titleCase("UAT_ONLY")).toBe("Uat Only");
    expect(titleCase("PRODUCTION")).toBe("Production");
  });
});

describe("toApiError", () => {
  it("reads the problem document the backend returns", async () => {
    const response = new Response(
      JSON.stringify({ status: 409, code: "ROTATION_WINDOW_OPEN", detail: "A key rotation is already in progress" }),
      { status: 409, headers: { "Content-Type": "application/problem+json" } },
    );
    const error = await toApiError(response);
    expect(error.status).toBe(409);
    expect(error.code).toBe("ROTATION_WINDOW_OPEN");
    expect(error.message).toContain("already in progress");
  });

  it("falls back to a readable message when the body is not JSON", async () => {
    const error = await toApiError(new Response("<html>", { status: 403 }));
    expect(error.code).toBe("HTTP_403");
    expect(error.message).toBe("You do not have access to this");
  });
});
