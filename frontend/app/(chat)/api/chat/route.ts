import { auth } from "@clerk/nextjs/server";
import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  generateId,
} from "ai";
import { BackendError, callBackend } from "@/lib/backend/client";
import {
  getChatById,
  saveChat,
  saveMessages,
  updateChatStatusById,
  updateChatTitleById,
} from "@/lib/db/queries";
import { ChatbotError, type ErrorCode } from "@/lib/errors";
import { generateUUID } from "@/lib/utils";

// Allow time for the real backend fiscal pipeline (ARCA WS calls, report
// build) on top of the AI SDK stream overhead. The BFF call itself uses a
// 60s timeout; this guards the whole serverless invocation.
export const maxDuration = 300;

// In-flight dedupe: the client (or a StrictMode double-effect / double click)
// can fire the same launch request twice. A second execution of the identical
// chat+message would duplicate the backend call and persisted messages. Track
// executions per chatId+message signature and short-circuit duplicates with a
// no-op stream (no chunks -> nothing is appended client-side).
const inFlightExecutions = new Map<string, true>();

// Structured response shape returned by the backend's POST /v1/chat/message
// (fiscal_agent/api/routes/chat.py -> ChatResponse).
interface ChatResponse {
  conversation_id: string;
  reply: string;
  actions_taken: string[];
  data: Record<string, unknown> | null;
}

interface HistoryEntry {
  role: "user" | "assistant";
  content: string;
}

interface ClientUIMessage {
  role?: string;
  content?: string | null;
  parts?: Array<{ type?: string; text?: string }>;
}

// Split a long reply into small stream deltas so the client renders text
// progressively instead of one large blob.
function chunkText(text: string, maxChunk = 80): string[] {
  const chunks: string[] = [];
  let current = "";
  const tokens = text.split(/(\s+)/);
  for (const token of tokens) {
    if ((current + token).length > maxChunk && current) {
      chunks.push(current);
      current = token;
    } else {
      current += token;
    }
  }
  if (current) {
    chunks.push(current);
  }
  return chunks;
}

// Flatten prior client messages into the backend's [{role, content}] history
// format. The operative last message is excluded; tool/non-text parts are
// skipped and client roles are mapped to the backend's user/assistant.
function buildHistory(uiMessages: ClientUIMessage[]): HistoryEntry[] {
  const history: HistoryEntry[] = [];
  for (const msg of uiMessages.slice(0, -1)) {
    if (msg.role !== "user" && msg.role !== "assistant") {
      continue;
    }
    const content =
      typeof msg.content === "string"
        ? msg.content
        : (msg.parts
            ?.filter((p) => p.type === "text")
            .map((p) => String(p.text ?? ""))
            .join("") ?? "");
    const trimmed = content.trim();
    if (!trimmed) {
      continue;
    }
    history.push({ role: msg.role, content: trimmed });
  }
  return history;
}

// Map a BFF/backend failure to the canonical ChatbotError code the client's
// onError handler understands (hooks/use-active-chat.tsx). The default 10s
// BFF timeout is not used here; the route passes its own 60s timeout.
function backendErrorToCode(err: BackendError): ErrorCode {
  if (err.status === 401) {
    return "unauthorized:chat";
  }
  if (err.status === 404) {
    return "not_found:chat";
  }
  if (err.status === 429) {
    return "rate_limit:chat";
  }
  if (err.status === 502 || err.status === 503 || err.status === 504) {
    return "offline:chat";
  }
  if (err.status >= 400 && err.status < 500) {
    return "bad_request:chat";
  }
  return "offline:chat";
}

function describeBackendError(err: unknown): {
  code: ErrorCode;
  detail: string;
} {
  if (err instanceof BackendError) {
    return { code: backendErrorToCode(err), detail: err.detail ?? err.message };
  }
  const detail = err instanceof Error ? err.message : String(err);
  return { code: "offline:chat", detail };
}

async function persistAssistantMessage(chatId: string, text: string) {
  if (!text) {
    return;
  }
  await saveMessages({
    messages: [
      {
        id: generateUUID(),
        chatId,
        role: "assistant",
        parts: [{ type: "text", text }],
        attachments: [],
        createdAt: new Date(),
      },
    ],
  });
}

/**
 * API Chat - Fiscal Console (backend-backed)
 * Forwards the user's natural language message to the real Python backend
 * (POST /v1/chat/message through the BFF client, which forwards the Clerk
 * JWT) and re-emits its reply as an AI SDK UI stream (text-start /
 * text-delta / text-end, data-chat-title) so the existing consumer
 * components need no changes.
 */
export async function POST(request: Request) {
  const body = await request.json();
  const {
    id,
    messages: initialMessages = [],
    message: singularMessage,
    isToolApprovalFlow,
    selectedVisibilityType,
  } = body;

  const visibility = selectedVisibilityType || "private";
  const uiMessages = singularMessage
    ? [singularMessage]
    : initialMessages || [];

  const { userId, orgId } = await auth();

  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  if (!orgId) {
    return new ChatbotError("forbidden:auth").toResponse();
  }

  try {
    const message = uiMessages.at(-1);
    if (!message) {
      return new ChatbotError("bad_request:api").toResponse();
    }

    // Persist initial message for chat history
    if (uiMessages.length === 1 && userId) {
      try {
        const existingChat = await getChatById({ id });
        if (!existingChat) {
          const rawText =
            typeof message.content === "string"
              ? message.content
              : message.parts?.find((p: any) => p.type === "text")?.text || "";
          const quickCuitMatch = rawText.match(/(\d{11})/);

          const now = new Date();
          const day = now.getDate().toString().padStart(2, "0");
          const month = (now.getMonth() + 1).toString().padStart(2, "0");
          const time = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;
          const timestamp = `${day}/${month} ${time}`;
          const title = quickCuitMatch
            ? `Informe ${quickCuitMatch[1]} — ${timestamp}`
            : `Consola Fiscal — ${timestamp}`;

          await saveChat({
            id,
            userId,
            tenantId: orgId,
            title,
            visibility,
            status: "running",
          });
        }

        await saveMessages({
          messages: [
            {
              id: generateUUID(),
              chatId: id,
              role: message.role,
              parts:
                message.parts ||
                (message.content
                  ? [{ type: "text", text: message.content }]
                  : []),
              attachments: message.attachments || [],
              createdAt: new Date(),
            },
          ],
        });
      } catch (e) {
        console.error("Historical persistence failed:", e);
      }
    }

    let userText = "";
    if (message.content && typeof message.content === "string") {
      userText = message.content.trim();
    } else if (message.parts) {
      userText = (
        message.parts
          ?.filter((p: any) => p.type === "text")
          .map((p: any) => String(p.text ?? ""))
          .join("") ?? ""
      ).trim();
    }

    const quickCuitMatch = userText.match(/(\d{11})/);
    const cuit = quickCuitMatch ? quickCuitMatch[1] : null;

    const executionKey = `${id}:${userText}`;
    if (inFlightExecutions.has(executionKey)) {
      console.log("Duplicate fiscal execution skipped:", executionKey);
      // No-op stream: no chunks -> the client appends nothing, so no
      // duplicated backend calls/messages reach the UI.
      const noopStream = createUIMessageStream({
        // Intentionally empty: a no-op stream appends nothing client-side.
        execute: async () => {
          await Promise.resolve();
        },
        generateId: generateUUID,
      });
      return createUIMessageStreamResponse({ stream: noopStream });
    }
    inFlightExecutions.set(executionKey, true);

    const streamInstance = createUIMessageStream({
      originalMessages: isToolApprovalFlow ? uiMessages : undefined,
      execute: async ({ writer: dataStream }) => {
        const textPartId = generateId();
        dataStream.write({ type: "text-start", id: textPartId });

        let assistantText = "";
        try {
          // The backend is the sole intent router: forward every message,
          // even ones without a CUIT — it answers with its help/UNKNOWN reply.
          const history = buildHistory(uiMessages as ClientUIMessage[]);
          const res = await callBackend<ChatResponse>("/v1/chat/message", {
            method: "POST",
            body: {
              message: userText,
              conversation_id: id,
              history: history.length ? history : null,
            },
            timeoutMs: 60_000,
          });

          assistantText = res.reply;
          if (res.data && typeof res.data === "object") {
            // Keep raw structured results visible for debugging.
            assistantText += `\n\n<details><summary>Datos</summary>\n\n\`\`\`json\n${JSON.stringify(res.data, null, 2)}\n\`\`\`\n\n</details>`;
          }

          for (const chunk of chunkText(assistantText)) {
            dataStream.write({
              type: "text-delta",
              id: textPartId,
              delta: chunk,
            });
          }
        } catch (err) {
          const { code, detail } = describeBackendError(err);
          assistantText = `No pude completar la consulta: ${detail}`;
          console.error(`[chat] backend chat request failed (${code}):`, err);
          dataStream.write({
            type: "text-delta",
            id: textPartId,
            delta: assistantText,
          });
        } finally {
          dataStream.write({ type: "text-end", id: textPartId });

          if (uiMessages.length === 1) {
            const now = new Date();
            const day = now.getDate().toString().padStart(2, "0");
            const month = (now.getMonth() + 1).toString().padStart(2, "0");
            const time = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;
            const timestamp = `${day}/${month} ${time}`;
            const title = cuit
              ? `Informe ${cuit} — ${timestamp}`
              : `Consulta Fiscal — ${timestamp}`;
            dataStream.write({ type: "data-chat-title", data: title });
            try {
              await updateChatTitleById({ chatId: id, title });
            } catch (titleErr) {
              console.error("Failed to save chat title:", titleErr);
            }
          }

          try {
            await persistAssistantMessage(id, assistantText);
          } catch (persistErr) {
            console.error("Failed to save assistant report:", persistErr);
          }

          try {
            await updateChatStatusById({ chatId: id, status: "done" });
          } catch (statusErr) {
            console.error("Failed to update chat status:", statusErr);
          }

          inFlightExecutions.delete(executionKey);
        }
      },
      generateId: generateUUID,
    });

    return createUIMessageStreamResponse({ stream: streamInstance });
  } catch (error) {
    console.error("Critical error in console API:", error);
    return new ChatbotError("offline:chat").toResponse();
  }
}

export function DELETE(_request: Request) {
  return Response.json({ success: true }, { status: 200 });
}
