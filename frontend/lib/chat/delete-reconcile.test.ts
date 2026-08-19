import { describe, expect, it } from "vitest";

import { reconcileChatsAfterDelete } from "./delete-reconcile";

// ── CD-4: sidebar history reconcile ─────────────────────────────────────────
// On a successful delete the sidebar removes the row from EVERY paginated
// history page; on failure it never drops the row (it revalidates instead).
// The helper is pure so the contract is testable without a React renderer.

interface Page<T> {
  chats: T[];
  hasMore: boolean;
}

describe("reconcileChatsAfterDelete (CD-4)", () => {
  const pages: Page<{ id: string; title: string }>[] = [
    {
      chats: [
        { id: "c1", title: "A" },
        { id: "c2", title: "B" },
      ],
      hasMore: true,
    },
    { chats: [{ id: "c3", title: "C" }], hasMore: false },
  ];

  it("removes the deleted chat from every page and keeps the rest", () => {
    const result = reconcileChatsAfterDelete(pages, "c2");

    expect(result[0].chats.map((c) => c.id)).toEqual(["c1"]);
    expect(result[1].chats.map((c) => c.id)).toEqual(["c3"]);
  });

  it("preserves page metadata (hasMore) untouched", () => {
    const result = reconcileChatsAfterDelete(pages, "c2");

    expect(result.map((p) => p.hasMore)).toEqual([true, false]);
  });

  it("returns the pages unchanged when there is no deletion pending", () => {
    expect(reconcileChatsAfterDelete(pages, null)).toBe(pages);
  });

  it("returns the pages unchanged when the chat id is not present", () => {
    const unchanged = reconcileChatsAfterDelete(pages, "missing");

    expect(unchanged).toEqual(pages);
    expect(unchanged[0].chats).toHaveLength(2);
  });
});
