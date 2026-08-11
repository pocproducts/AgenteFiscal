import { describe, expect, it } from "vitest";
import { ChatbotError } from "./errors";

describe("ChatbotError", () => {
  it("derives the HTTP status code from the error type", () => {
    const cases: [ConstructorParameters<typeof ChatbotError>[0], number][] = [
      ["bad_request:api", 400],
      ["unauthorized:auth", 401],
      ["forbidden:auth", 403],
      ["not_found:chat", 404],
      ["rate_limit:chat", 429],
      ["offline:chat", 503],
    ];

    for (const [code, status] of cases) {
      expect(new ChatbotError(code).statusCode).toBe(status);
    }
  });

  it("toResponse() body carries the canonical {code, cause} shape", async () => {
    const response = new ChatbotError(
      "bad_request:api",
      "Parameter chatId is required."
    ).toResponse();

    expect(response.status).toBe(400);
    const body = await response.json();
    expect(body.code).toBe("bad_request:api");
    expect(body.cause).toBe("Parameter chatId is required.");
    expect(typeof body.message).toBe("string");
  });

  it("database-surface errors never leak cause/message to the client", async () => {
    const response = new ChatbotError(
      "bad_request:database",
      "duplicate key value violates unique constraint"
    ).toResponse();

    const body = await response.json();
    expect(body.code).toBe("");
    expect(body.message).not.toContain("duplicate key");
    expect(body.cause).toBeUndefined();
  });
});
