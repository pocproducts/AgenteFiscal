/**
 * Pure reconciliation helper for the sidebar history list (CD-4).
 *
 * Lives outside the component so the delete-reconcile contract is
 * unit-testable without a React renderer: on a successful delete the sidebar
 * removes the row from every paginated history page; on failure it revalidates
 * instead (the optimistic removal never happens).
 *
 * The page type `P` is preserved untouched (e.g. ChatHistory keeps its
 * `hasMore` flag) — only the `chats` array is filtered.
 */
export function reconcileChatsAfterDelete<
  T extends { id: string },
  P extends { chats: T[] },
>(chatHistories: P[], deletedId: string | null): P[] {
  if (!deletedId) {
    return chatHistories;
  }
  return chatHistories.map((chatHistory) => ({
    ...chatHistory,
    chats: chatHistory.chats.filter((chat) => chat.id !== deletedId),
  })) as P[];
}
