import { describe, expect, it } from "vitest";
import { generateUUID, interpolate, sanitizeText } from "./utils";

describe("interpolate", () => {
  it("fills a single placeholder", () => {
    expect(interpolate("Hello {name}!", { name: "World" })).toBe(
      "Hello World!"
    );
  });

  it("fills multiple placeholders", () => {
    expect(
      interpolate("{completed} task{done} done", {
        completed: 3,
        done: "s",
      })
    ).toBe("3 tasks done");
  });

  it("supports the empty-string plural case", () => {
    expect(
      interpolate("{completed} task{done} done", { completed: 1, done: "" })
    ).toBe("1 task done");
  });

  it("leaves unmatched placeholders untouched", () => {
    expect(interpolate("Hi {name}, {unknown}", { name: "A" })).toBe(
      "Hi A, {unknown}"
    );
  });

  it("replaces every occurrence of a repeated key", () => {
    expect(interpolate("{x}-{x}", { x: "a" })).toBe("a-a");
  });
});

describe("sanitizeText", () => {
  it("strips the has_function_call marker", () => {
    expect(sanitizeText("hello<has_function_call>world")).toBe("helloworld");
  });

  it("returns unrelated text unchanged", () => {
    expect(sanitizeText("plain text")).toBe("plain text");
  });
});

describe("generateUUID", () => {
  it("matches the v4 UUID shape", () => {
    const uuid = generateUUID();
    expect(uuid).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
    );
  });

  it("generates distinct values", () => {
    expect(generateUUID()).not.toBe(generateUUID());
  });
});
