import "server-only";

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import type { ArtifactKind } from "@/components/chat/artifact";
import type { VisibilityType } from "@/components/chat/visibility-selector";
import { ChatbotError } from "@/lib/errors";
import { generateUUID } from "@/lib/utils";
import type {
  Chat,
  DBMessage,
  Document,
  Suggestion,
  User,
  Vote,
  Tenant,
  TenantMember,
} from "./schema";

/**
 * DEPRECATED in-memory mock database persisted to a JSON file.
 *
 * The chat-history surface (chats/messages list, delete, delete-all) is now
 * handled by the real backend (Postgres): the BFF routes call
 * `frontend/lib/backend/conversations.ts` → /v1/conversations. The chat
 * functions below (saveChat / saveMessages / getChatsByUserId /
 * deleteAllChatsByUserId / getMessagesByChatId) are no longer wired into
 * the chat flow and should NOT be re-used — they are kept only because the
 * documents/suggestions/vote/mail surfaces still depend on this store until
 * those migrations land.
 *
 * Why file-backed + globalThis singleton:
 * - Next.js bundles Server Actions and Route Handlers separately, so module-level
 *   arrays are NOT shared between `register()` (action) and the NextAuth
 *   credentials `authorize()` (route handler). The file + globalThis bridge
 *   closes that gap: both sides read/write the same state object/disk file.
 * - Persistence survives dev server restarts and Fast Refresh rebuilds.
 * - Set `MOCK_DB_PATH` to relocate the file (e.g. for tests).
 */

type MockState = {
  users: User[];
  chats: Chat[];
  messages: DBMessage[];
  votes: Vote[];
  documents: Document[];
  suggestions: Suggestion[];
  tenants: Tenant[];
  tenantMembers: TenantMember[];
};

const DB_PATH =
  process.env.MOCK_DB_PATH ?? join(process.cwd(), ".data", "db.json");

const EMPTY_STATE = (): MockState => ({
  users: [],
  chats: [],
  messages: [],
  votes: [],
  documents: [],
  suggestions: [],
  tenants: [],
  tenantMembers: [],
});

function reviveDates(state: MockState): MockState {
  const toDate = (value: unknown) =>
    typeof value === "string" ? new Date(value) : value;

  state.users = (state.users ?? []).map((u) => ({
    ...u,
    createdAt: toDate(u.createdAt) as Date,
    updatedAt: toDate(u.updatedAt) as Date,
  }));
  state.chats = (state.chats ?? []).map((c) => ({
    ...c,
    createdAt: toDate(c.createdAt) as Date,
  }));
  state.messages = (state.messages ?? []).map((m) => ({
    ...m,
    createdAt: toDate(m.createdAt) as Date,
  }));
  state.documents = (state.documents ?? []).map((d) => ({
    ...d,
    createdAt: toDate(d.createdAt) as Date,
  }));
  state.suggestions = (state.suggestions ?? []).map((s) => ({
    ...s,
    documentCreatedAt: toDate(s.documentCreatedAt) as Date,
    createdAt: toDate(s.createdAt) as Date,
  }));
  state.tenants = (state.tenants ?? []).map((t) => ({
    ...t,
    createdAt: toDate(t.createdAt) as Date,
  }));
  return state;
}

function loadState(): MockState {
  if (!existsSync(DB_PATH)) {
    return EMPTY_STATE();
  }
  try {
    const raw = readFileSync(DB_PATH, "utf8");
    const state = reviveDates({
      ...EMPTY_STATE(),
      ...(JSON.parse(raw) as MockState),
    });
    // Ephemeral history: clear all chat/report history on every server boot so
    // the panel always starts empty. Auth/tenants are preserved; the history
    // will be owned by the real backend once the migration starts.
    state.chats = [];
    state.messages = [];
    state.votes = [];
    state.documents = [];
    state.suggestions = [];
    return state;
  } catch (_error) {
    // Corrupt or unreadable mock file: start fresh instead of crashing the app.
    return EMPTY_STATE();
  }
}

function persistState() {
  mkdirSync(dirname(DB_PATH), { recursive: true });
  writeFileSync(DB_PATH, JSON.stringify(state), "utf8");
}

const globalForMock = globalThis as unknown as { __chatbotMockDb?: MockState };
const state: MockState =
  globalForMock.__chatbotMockDb ?? (globalForMock.__chatbotMockDb = loadState());

const { users, chats, messages, votes, documents, suggestions, tenants, tenantMembers } = state;

export async function saveChat({
  id,
  userId,
  tenantId,
  title,
  visibility,
  status,
}: {
  id: string;
  userId: string;
  tenantId: string;
  title: string;
  visibility: VisibilityType;
  status: "running" | "done";
}) {
  await Promise.resolve();
  try {
    const newChat: Chat = {
      id,
      createdAt: new Date(),
      userId,
      tenantId,
      title,
      visibility: visibility as "public" | "private",
      status,
    };
    chats.push(newChat);
    persistState();
    return newChat;
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to save chat");
  }
}

export async function deleteAllChatsByUserId({
  userId,
  tenantId,
}: {
  userId: string;
  tenantId: string;
}) {
  await Promise.resolve();
  try {
    const userChats = chats.filter(
      (c) => c.userId === userId && c.tenantId === tenantId
    );
    const chatIds = userChats.map((c) => c.id);

    // Delete associated votes
    for (let i = votes.length - 1; i >= 0; i--) {
      if (chatIds.includes(votes[i].chatId)) {
        votes.splice(i, 1);
      }
    }

    // Delete associated messages
    for (let i = messages.length - 1; i >= 0; i--) {
      if (chatIds.includes(messages[i].chatId)) {
        messages.splice(i, 1);
      }
    }

    // Delete chats
    let deletedCount = 0;
    for (let i = chats.length - 1; i >= 0; i--) {
      if (chats[i].userId === userId && chats[i].tenantId === tenantId) {
        chats.splice(i, 1);
        deletedCount++;
      }
    }

    persistState();
    return { deletedCount };
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to delete all chats by user id"
    );
  }
}

export async function getChatsByUserId({
  id,
  tenantId,
  limit,
  startingAfter,
  endingBefore,
}: {
  id: string;
  tenantId: string;
  limit: number;
  startingAfter: string | null;
  endingBefore: string | null;
}) {
  await Promise.resolve();
  try {
    let filteredChats = chats.filter(
      (c) => c.userId === id && c.tenantId === tenantId
    );

    // Sort by createdAt descending
    filteredChats.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());

    if (startingAfter) {
      const selectedChat = chats.find((c) => c.id === startingAfter);
      if (!selectedChat) {
        throw new ChatbotError(
          "not_found:database",
          `Chat with id ${startingAfter} not found`
        );
      }
      filteredChats = filteredChats.filter(
        (c) => c.createdAt.getTime() < selectedChat.createdAt.getTime()
      );
    } else if (endingBefore) {
      const selectedChat = chats.find((c) => c.id === endingBefore);
      if (!selectedChat) {
        throw new ChatbotError(
          "not_found:database",
          `Chat with id ${endingBefore} not found`
        );
      }
      filteredChats = filteredChats.filter(
        (c) => c.createdAt.getTime() > selectedChat.createdAt.getTime()
      );
    }

    const hasMore = filteredChats.length > limit;
    const resultChats = hasMore ? filteredChats.slice(0, limit) : filteredChats;

    return {
      chats: resultChats,
      hasMore,
    };
  } catch (_error) {
    if (_error instanceof ChatbotError) {
      throw _error;
    }
    throw new ChatbotError(
      "bad_request:database",
      "Failed to get chats by user id"
    );
  }
}

export async function getChatById({ id }: { id: string }) {
  await Promise.resolve();
  try {
    const selectedChat = chats.find((c) => c.id === id);
    return selectedChat || null;
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to get chat by id");
  }
}

export async function saveMessages({
  messages: newMsgs,
}: {
  messages: DBMessage[];
}) {
  await Promise.resolve();
  try {
    messages.push(...newMsgs);
    persistState();
    return newMsgs;
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to save messages");
  }
}

export async function getMessagesByChatId({ id }: { id: string }) {
  await Promise.resolve();
  try {
    const chatMsgs = messages.filter((m) => m.chatId === id);
    chatMsgs.sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime());
    return chatMsgs;
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to get messages by chat id"
    );
  }
}

export async function markChatMailSent({
  chatId,
  email,
}: {
  chatId: string;
  email: string;
}): Promise<boolean> {
  await Promise.resolve();
  try {
    let changed = false;
    for (const msg of messages) {
      if (msg.chatId !== chatId || msg.role !== "assistant") {
        continue;
      }
      const parts = msg.parts as Array<{ type: string; text?: unknown }>;
      if (!Array.isArray(parts)) {
        continue;
      }
      for (const part of parts) {
        if (
          part?.type === "text" &&
          typeof part.text === "string" &&
          (part.text.includes("[MAIL_INPUT_REPLACEMENT]") ||
            part.text.includes("[MAIL_INPUT_REPLACEMENT:"))
        ) {
          part.text = part.text.replace(
            /\[MAIL_INPUT_REPLACEMENT(?::[A-Za-z0-9_-]+)?\]/g,
            `[MAIL_SENT:${email}]`
          );
          changed = true;
        }
      }
    }
    if (changed) {
      persistState();
      return true;
    }
    return false;
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to mark chat mail sent"
    );
  }
}

export async function voteMessage({
  chatId,
  messageId,
  type,
}: {
  chatId: string;
  messageId: string;
  type: "up" | "down";
}) {
  await Promise.resolve();
  try {
    const existingVote = votes.find(
      (v) => v.messageId === messageId && v.chatId === chatId
    );
    if (existingVote) {
      existingVote.isUpvoted = type === "up";
      persistState();
      return existingVote;
    }
    const newVote: Vote = {
      chatId,
      messageId,
      isUpvoted: type === "up",
    };
    votes.push(newVote);
    persistState();
    return newVote;
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to vote message");
  }
}

export async function getVotesByChatId({ id }: { id: string }) {
  await Promise.resolve();
  try {
    return votes.filter((v) => v.chatId === id);
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to get votes by chat id"
    );
  }
}

export async function saveDocument({
  id,
  title,
  kind,
  content,
  userId,
  tenantId,
}: {
  id: string;
  title: string;
  kind: ArtifactKind;
  content: string;
  userId: string;
  tenantId: string;
}) {
  await Promise.resolve();
  try {
    const newDoc: Document = {
      id,
      title,
      kind: kind as any,
      content,
      userId,
      tenantId,
      createdAt: new Date(),
    };
    documents.push(newDoc);
    persistState();
    return [newDoc];
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to save document");
  }
}

export async function updateDocumentContent({
  id,
  content,
}: {
  id: string;
  content: string;
}) {
  await Promise.resolve();
  try {
    const docs = documents.filter((d) => d.id === id);
    docs.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());

    const latest = docs[0];
    if (!latest) {
      throw new ChatbotError("not_found:database", "Document not found");
    }

    const updatedDoc: Document = {
      ...latest,
      content,
      createdAt: new Date(),
    };
    documents.push(updatedDoc);
    persistState();
    return [updatedDoc];
  } catch (_error) {
    if (_error instanceof ChatbotError) {
      throw _error;
    }
    throw new ChatbotError(
      "bad_request:database",
      "Failed to update document content"
    );
  }
}

export async function getDocumentsById({ id }: { id: string }) {
  await Promise.resolve();
  try {
    const docs = documents.filter((d) => d.id === id);
    docs.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
    return docs;
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to get documents by id"
    );
  }
}

export async function getDocumentById({ id }: { id: string }) {
  await Promise.resolve();
  try {
    const docs = documents.filter((d) => d.id === id);
    if (docs.length === 0) {
      return undefined;
    }
    docs.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
    return docs[0];
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to get document by id"
    );
  }
}

export async function deleteDocumentsByIdAfterTimestamp({
  id,
  timestamp,
}: {
  id: string;
  timestamp: Date;
}) {
  await Promise.resolve();
  try {
    // Delete suggestions
    for (let i = suggestions.length - 1; i >= 0; i--) {
      if (
        suggestions[i].documentId === id &&
        suggestions[i].documentCreatedAt.getTime() > timestamp.getTime()
      ) {
        suggestions.splice(i, 1);
      }
    }

    const deletedDocs: Document[] = [];
    for (let i = documents.length - 1; i >= 0; i--) {
      if (
        documents[i].id === id &&
        documents[i].createdAt.getTime() > timestamp.getTime()
      ) {
        const [removed] = documents.splice(i, 1);
        deletedDocs.push(removed);
      }
    }
    persistState();
    return deletedDocs;
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to delete documents by id after timestamp"
    );
  }
}

export async function saveSuggestions({
  suggestions: newSuggestions,
}: {
  suggestions: Suggestion[];
}) {
  await Promise.resolve();
  try {
    suggestions.push(...newSuggestions);
    persistState();
    return newSuggestions;
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to save suggestions"
    );
  }
}

export async function getSuggestionsByDocumentId({
  documentId,
}: {
  documentId: string;
}) {
  await Promise.resolve();
  try {
    return suggestions.filter((s) => s.documentId === documentId);
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to get suggestions by document id"
    );
  }
}

export async function getMessageById({ id }: { id: string }) {
  await Promise.resolve();
  try {
    return messages.filter((m) => m.id === id);
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to get message by id"
    );
  }
}

export async function deleteMessagesByChatIdAfterTimestamp({
  chatId,
  timestamp,
}: {
  chatId: string;
  timestamp: Date;
}) {
  await Promise.resolve();
  try {
    const msgsToDelete = messages.filter(
      (m) => m.chatId === chatId && m.createdAt.getTime() >= timestamp.getTime()
    );
    const msgIds = msgsToDelete.map((m) => m.id);

    if (msgIds.length > 0) {
      // Delete votes
      for (let i = votes.length - 1; i >= 0; i--) {
        if (votes[i].chatId === chatId && msgIds.includes(votes[i].messageId)) {
          votes.splice(i, 1);
        }
      }

      // Delete messages
      const deletedMsgs: DBMessage[] = [];
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].chatId === chatId && msgIds.includes(messages[i].id)) {
          const [removed] = messages.splice(i, 1);
          deletedMsgs.push(removed);
        }
      }
      persistState();
      return deletedMsgs;
    }
    return [];
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to delete messages by chat id after timestamp"
    );
  }
}

export async function updateChatVisibilityById({
  chatId,
  visibility,
}: {
  chatId: string;
  visibility: "private" | "public";
}) {
  await Promise.resolve();
  try {
    const chat = chats.find((c) => c.id === chatId);
    if (chat) {
      chat.visibility = visibility;
      persistState();
      return [chat];
    }
    return [];
  } catch (_error) {
    throw new ChatbotError(
      "bad_request:database",
      "Failed to update chat visibility by id"
    );
  }
}

export async function updateChatTitleById({
  chatId,
  title,
}: {
  chatId: string;
  title: string;
}) {
  await Promise.resolve();
  try {
    const chat = chats.find((c) => c.id === chatId);
    if (chat) {
      chat.title = title;
      persistState();
      return [chat];
    }
    return [];
  } catch (_error) {
    return [];
  }
}

export async function updateChatStatusById({
  chatId,
  status,
}: {
  chatId: string;
  status: "running" | "done";
}) {
  await Promise.resolve();
  try {
    const chat = chats.find((c) => c.id === chatId);
    if (chat) {
      chat.status = status;
      persistState();
      return [chat];
    }
    return [];
  } catch (_error) {
    return [];
  }
}

export async function saveChatActivity({
  chatId,
  activity,
}: {
  chatId: string;
  activity: unknown;
}) {
  await Promise.resolve();
  try {
    const chat = chats.find((c) => c.id === chatId);
    if (chat) {
      chat.agentActivity = activity;
      persistState();
      return [chat];
    }
    return [];
  } catch (_error) {
    return [];
  }
}

export async function getTenantById(id: string): Promise<Tenant | null> {
  await Promise.resolve();
  try {
    return tenants.find((t) => t.id === id) || null;
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to get tenant by id");
  }
}

export async function getTenantByUser(userId: string, tenantId: string): Promise<Tenant | null> {
  await Promise.resolve();
  try {
    const membership = tenantMembers.find((m) => m.userId === userId && m.tenantId === tenantId);
    if (!membership) return null;
    return tenants.find((t) => t.id === tenantId) || null;
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to get tenant by user");
  }
}

export async function listTenantsForUser(userId: string): Promise<Tenant[]> {
  await Promise.resolve();
  try {
    const userMemberships = tenantMembers.filter((m) => m.userId === userId);
    const tenantIds = userMemberships.map((m) => m.tenantId);
    return tenants.filter((t) => tenantIds.includes(t.id));
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to list tenants for user");
  }
}

export async function createTenant(userId: string, name: string): Promise<Tenant> {
  await Promise.resolve();
  try {
    const id = generateUUID();
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    const newTenant: Tenant = {
      id,
      name,
      slug,
      ownerUserId: userId,
      createdAt: new Date(),
    };
    tenants.push(newTenant);
    tenantMembers.push({
      tenantId: id,
      userId,
    });
    persistState();
    return newTenant;
  } catch (_error) {
    throw new ChatbotError("bad_request:database", "Failed to create tenant");
  }
}

