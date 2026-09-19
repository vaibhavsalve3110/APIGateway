import { describe, expect, it } from "vitest";

import { fillPath, inferFields, isValidJson, mergeFields, pathParams, prettyJson } from "./docs";

describe("inferFields", () => {
  it("derives nested field names and types from an example", () => {
    const fields = inferFields('{"txnId":"IMPS1","amount":250.5,"count":3,"ok":true,"payee":{"ifsc":"HDFC0000123"},"items":[{"sku":"A"}]}');
    expect(fields.map((f) => [f.name, f.type])).toEqual([
      ["txnId", "string"],
      ["amount", "number"],
      ["count", "integer"],
      ["ok", "boolean"],
      ["payee", "object"],
      ["payee.ifsc", "string"],
      ["items", "array"],
      ["items[].sku", "string"],
    ]);
    expect(fields[0]!.example).toBe("IMPS1");
    expect(fields[4]!.example).toBeNull();
  });

  it("returns nothing for invalid or empty JSON", () => {
    expect(inferFields("{not json")).toEqual([]);
    expect(inferFields("")).toEqual([]);
  });
});

describe("mergeFields", () => {
  it("keeps what the author already wrote for surviving fields", () => {
    const merged = mergeFields(
      [{ name: "amount", type: "string(decimal)", required: true, example: "1", description: "INR" }],
      inferFields('{"amount":"250.00","remarks":"x"}'),
    );
    expect(merged[0]).toMatchObject({ name: "amount", type: "string(decimal)", required: true, description: "INR", example: "250.00" });
    expect(merged[1]).toMatchObject({ name: "remarks", required: false });
  });
});

describe("path parameters", () => {
  it("lists and fills {param} segments", () => {
    expect(pathParams("/v1/accounts/{accountId}/txns/{txnId}")).toEqual(["accountId", "txnId"]);
    expect(fillPath("/v1/x/{id}/y/{other}", { id: "A 1/2" })).toBe("/v1/x/A%201%2F2/y/{other}");
  });
});

describe("json helpers", () => {
  it("pretty-prints JSON and leaves other text alone", () => {
    expect(prettyJson('{"a":1}')).toBe('{\n  "a": 1\n}');
    expect(prettyJson("plain text")).toBe("plain text");
    expect(isValidJson("")).toBe(true);
    expect(isValidJson("{")).toBe(false);
  });
});
