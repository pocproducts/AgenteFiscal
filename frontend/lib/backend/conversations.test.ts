import { beforeEach, describe, expect, it, vi } from "vitest";

// The BFF client holds the Clerk JWT and must never touch the browser; for
// unit tests only callBackend is replaced, BackendError stays real so the
// status contract (CD-3) is asserted with the authentic error type.
const { callBackend } = vi.hoisted(() => ({ callBackend: vi.fn() }));

vi.mock("@/lib/backend/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/backend/client")>();
  return { ...actual, callBackend };
});

import { BackendError } from "@/lib/backend/client";
import {
  buildDeleteChatResponse,
  deleteConversation,
  patchConversationTitle,
} from "./conversations";

beforeEach(() => {
  vi.clearAllMocks();
});

// ── CD-3: deleteConversation maps the backend 404 honestly ──────────────────
// The backend tombstones on DELETE (204) or 404s for missing / already-deleted
// / cross-tenant rows. The client helper must turn that 404 into a REAL
// failure result (`deleted: false`) — never a swallowed success — so the BFF
// responds `{success:false, deleted:false}` and the sidebar keeps the row.

describe("deleteConversation (CD-3)", () => {
  it("returns {deleted:true} when the backend tombstones the row (204)", async () => {
    callBackend.mockResolvedValue(undefined);

    const result = await deleteConversation("conv-1");

    expect(result).toEqual({ deleted: true });
    expect(callBackend).toHaveBeenCalledWith("/v1/conversations/conv-1", {
      method: "DELETE",
      timeoutMs: 60_000,
    });
  });

  it("maps a backend 404 to {deleted:false} instead of throwing", async () => {
    callBackend.mockRejectedValue(new BackendError("not found", 404));

    await expect(deleteConversation("conv-1")).resolves.toEqual({
      deleted: false,
    });
  });

  it("rethrows non-404 backend failures (5xx stays a failure)", async () => {
    callBackend.mockRejectedValue(new BackendError("boom", 503));

    await expect(deleteConversation("conv-1")).rejects.toBeInstanceOf(
      BackendError
    );
  });
});

// ── CD-2: patchConversationTitle PATCHes and never creates ──────────────────
// Title saves map to PATCH /v1/conversations/{id} (title-only, no-create). A
// 404 means the chat was deleted — `{ok:false}`, no row resurrected.

describe("patchConversationTitle (CD-2)", () => {
  it("PATCHes the title and returns {ok:true}", async () => {
    callBackend.mockResolvedValue({ conversation_id: "conv-1" });

    const result = await patchConversationTitle("conv-1", "Mi informe");

    expect(result).toEqual({ ok: true });
    expect(callBackend).toHaveBeenCalledWith("/v1/conversations/conv-1", {
      method: "PATCH",
      body: { title: "Mi informe" },
      timeoutMs: 60_000,
    });
  });

  it("returns {ok:false} on 404 (deleted chat is never resurrected)", async () => {
    callBackend.mockRejectedValue(new BackendError("not found", 404));

    await expect(
      patchConversationTitle("conv-1", "Mi informe")
    ).resolves.toEqual({ ok: false });
  });

  it("rethrows non-404 backend failures", async () => {
    callBackend.mockRejectedValue(new BackendError("offline", 503));

    await expect(
      patchConversationTitle("conv-1", "Mi informe")
    ).rejects.toBeInstanceOf(BackendError);
  });
});

// ── CD-3: the BFF DELETE envelope is honest ─────────────────────────────────
// The route responds `{success, deleted}`: success only when the backend
// really deleted. A second delete (404) must produce `{success:false,
// deleted:false}` so the client never reports success for a failed delete.

describe("buildDeleteChatResponse (CD-3 envelope)", () => {
  it("reports success only when the backend really deleted", () => {
    expect(buildDeleteChatResponse(true)).toEqual({
      success: true,
      deleted: true,
    });
  });

  it("propagates failure as {success:false, deleted:false}", () => {
    expect(buildDeleteChatResponse(false)).toEqual({
      success: false,
      deleted: false,
    });
  });
});
