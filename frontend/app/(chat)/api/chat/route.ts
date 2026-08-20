import { auth } from "@clerk/nextjs/server";
import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  generateId,
} from "ai";
import {
  AGENT_SESSION_WINDOW_MS,
  NO_MONITOR_TOOLS,
  TOOL_KEYS_RE_GLOBAL,
  TOOL_NAMES,
  TOOL_WINDOW_OVERRIDES,
} from "@/lib/agent-window";
import {
  BackendError,
  callBackend,
  callBackendStream,
} from "@/lib/backend/client";
import {
  buildDeleteChatResponse,
  deleteConversation,
  patchConversationTitle,
} from "@/lib/backend/conversations";
import { ChatbotError, type ErrorCode } from "@/lib/errors";
import { tenantKey } from "@/lib/tenant";
import { generateUUID } from "@/lib/utils";

// Allow time for the real backend fiscal pipeline (ARCA WS calls, report
// build) on top of the AI SDK stream overhead. The BFF call itself uses a
// 60s timeout; this guards the whole serverless invocation.
export const maxDuration = 600;

// In-flight dedupe: the client (or a StrictMode double-effect / double click)
// can fire the same launch request twice. A second execution of the identical
// chat+message would duplicate the backend call and persisted messages. Track
// executions per chatId+message signature and short-circuit duplicates with a
// no-op stream (no chunks -> nothing is appended client-side).
const inFlightExecutions = new Map<string, true>();

// Structured response shape returned by the backend's POST /v1/chat/message
// (agente_fiscal/api/routes/chat.py -> ChatResponse).
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

// Conversation title: `Informe {cuit} — {DD/MM HH:MM}` for fiscal chats, a
// generic fallback otherwise. Shared by the tool branch (emitted at stream
// start so the sidebar shows it while the run is live) and the finally block
// (non-tool chats, after the stream completes) so both use the exact same
// format and em-dash.
function buildChatTitle(cuit: string | null, now: Date): string {
  const day = now.getDate().toString().padStart(2, "0");
  const month = (now.getMonth() + 1).toString().padStart(2, "0");
  const time = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;
  const timestamp = `${day}/${month} ${time}`;
  return cuit
    ? `Informe ${cuit} — ${timestamp}`
    : `Consulta Fiscal — ${timestamp}`;
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

// ── Browser tools: real backend wiring (Route BFF) ────────────────────────────
// The BFF forwards the message to POST /v1/chat/message, which runs the real
// backend automation (agente_fiscal/api/routes/chat.py -> ToolSpec dispatch:
// ComposioBrowser for browser tools, padrón A5 / rules engine for deterministic
// ones) and returns the tool data (incl. live_url) + a formatted markdown
// reply. We map that into the agent-sidebar SSE events the UI already consumes.

// Keep the live browser + agent monitor open for the tool's window (counted
// from command fire), even if the backend finishes the run earlier. Single
// source of truth lives in `lib/agent-window.ts` — change the window there and
// both this route and the streamed UI contract move together.

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
    profileId,
  } = body;

  const activeProfileId =
    typeof profileId === "string" && profileId.trim() ? profileId.trim() : null;

  const uiMessages = singularMessage
    ? [singularMessage]
    : initialMessages || [];

  const { userId, orgId } = await auth();
  const tenant = tenantKey(orgId, userId);

  if (!userId || !tenant) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  try {
    const message = uiMessages.at(-1);
    if (!message) {
      return new ChatbotError("bad_request:api").toResponse();
    }

    // Message/conversation persistence is owned by the backend: both
    // /v1/chat/message and /v1/chat/message/stream upsert the conversation
    // (user + assistant) in Postgres themselves. Nothing to save here.

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

        // Title sent at stream start (tool branch) → the finally block skips
        // re-emitting/re-patching it for the same conversation.
        let titleSent = false;
        let assistantText = "";
        try {
          // Browser tools: resolve toolKey/toolName/windowMs from the matcher
          // (single source: lib/agent-window.ts). Non-tool messages AND
          // deterministic engines (consultaarca / calendariovencimientosarca)
          // go through the generic backend chat path below — they must NOT
          // open the agent monitor.
          // Multi-tool: parse EVERY tool token in the message (not just the
          // first). When `tools` is forwarded, the backend bypasses its
          // single-intent detect() and runs the selection as ONE consolidated
          // pipeline. Single-tool messages behave exactly like before.
          const toolKeys = [
            ...new Set(
              (userText.match(TOOL_KEYS_RE_GLOBAL) ?? []).map((m) =>
                m.toLowerCase()
              )
            ),
          ];
          const hasToolCommand = toolKeys.length > 0;
          const selectedBrowserTools = toolKeys.filter(
            (k): k is string =>
              Boolean(TOOL_NAMES[k]) &&
              !(NO_MONITOR_TOOLS as readonly string[]).includes(k)
          );
          // `informefiscal` means ALL data tools (incl. browser); `enviarmail`
          // alone is a pure send action and never opens the agent monitor.
          const opensMonitor =
            toolKeys.includes("informefiscal") ||
            selectedBrowserTools.length > 0;
          // Deterministic engines already reply with rich markdown, so skip the
          // verbose raw data dump for them exactly like today.
          const suppressJsonDump =
            hasToolCommand &&
            !toolKeys.includes("informefiscal") &&
            toolKeys.every(
              (k) =>
                (NO_MONITOR_TOOLS as readonly string[]).includes(k) ||
                k === "enviarmail"
            );

          if (hasToolCommand && opensMonitor) {
            // ── Browser tool: real backend wiring (Route BFF → /v1/chat/message/stream) ──
            // The backend runs the real automation (ComposioBrowser o motor
            // determinista según ToolSpec) and returns the tool data (incl.
            // live_url) + a formatted markdown reply. We map that into the
            // agent-sidebar SSE events the UI already consumes.
            // Tool window (used in session-start AND the remaining-window wait).
            // ONE consolidated session for the whole selection: `informefiscal`
            // (implies every data tool) names the session; otherwise the first
            // selected browser tool. Window = the LONGEST selected browser
            // window, so the UI never closes before the pipeline finishes.
            const windowCandidateKeys = toolKeys.includes("informefiscal")
              ? [
                  "sistemaregistral",
                  "deudavencimientos",
                  "misfacilidades",
                  "rentascordoba",
                ]
              : selectedBrowserTools;
            const windowMs = Math.max(
              ...windowCandidateKeys.map(
                (k) => TOOL_WINDOW_OVERRIDES[k] ?? AGENT_SESSION_WINDOW_MS
              )
            );
            const agentId = generateId();
            const toolKey = toolKeys.includes("informefiscal")
              ? "informefiscal"
              : selectedBrowserTools[0];
            const toolName = toolKeys.includes("informefiscal")
              ? "InformeFiscal"
              : (TOOL_NAMES[toolKey] ?? "Fiscal");

            // 1) Open the agent monitor immediately (optimistic) so the sidebar
            //    appears the instant the command fires, while the backend runs.
            dataStream.write({
              type: "data-agent-session-start",
              data: {
                agentId,
                toolName,
                toolKey,
                profileId: activeProfileId ?? undefined,
                tasks: [],
                // UI contract: how long the live session window lasts. The monitor
                // clock and the "sesiones de agentes" table read this value, so a
                // change in `lib/agent-window.ts` propagates everywhere at once.
                windowMs,
              },
            });

            // Window clock starts the moment the monitor opens.
            const startedAt = Date.now();

            // 2) Run the real backend automation via SSE so the LIVE browser URL
            //    arrives mid-run (while the Composio session is still alive), not
            //    after the ~3min run completes (when it would already be dead).
            const history = buildHistory(uiMessages as ClientUIMessage[]);
            try {
              const streamRes = await callBackendStream(
                "/v1/chat/message/stream",
                {
                  method: "POST",
                  body: {
                    message: userText,
                    conversation_id: id,
                    history: history.length ? history : null,
                    profile_id: activeProfileId ?? undefined,
                    tools: hasToolCommand ? toolKeys : undefined,
                  },
                  timeoutMs: 600_000,
                }
              );

              if (!streamRes.body) {
                throw new Error("Backend stream response has no body");
              }
              const reader = streamRes.body.getReader();
              const decoder = new TextDecoder();
              let buffer = "";
              let finalReply = "";
              let finalData: Record<string, unknown> | null = null;

              // Conversation row now exists (backend persists it running at dispatch;
              // once the stream connected, the dispatch persist is guaranteed done).
              // PATCH the friendly title first (CD-2: PATCH never creates, but the row
              // exists now), then emit data-chat-title so the sidebar revalidation this
              // event triggers reads the saved title.
              const titleAtStart =
                uiMessages.length === 1 && cuit
                  ? buildChatTitle(cuit, new Date())
                  : null;
              if (titleAtStart) {
                try {
                  const { ok } = await patchConversationTitle(id, titleAtStart);
                  if (!ok) {
                    console.error(
                      "Chat title not saved: conversation missing or deleted:",
                      id
                    );
                  }
                } catch (titleErr) {
                  console.error("Failed to save chat title:", titleErr);
                }
                dataStream.write({
                  type: "data-chat-title",
                  data: titleAtStart,
                });
                titleSent = true;
              }

              while (true) {
                const { done, value } = await reader.read();
                if (done) {
                  break;
                }
                buffer += decoder.decode(value, { stream: true });
                let sep = buffer.indexOf("\n\n");
                while (sep !== -1) {
                  const frame = buffer.slice(0, sep);
                  buffer = buffer.slice(sep + 2);

                  let event = "message";
                  let data = "";
                  for (const line of frame.split("\n")) {
                    if (line.startsWith("event:")) {
                      event = line.slice(6).trim();
                    } else if (line.startsWith("data:")) {
                      data += line.slice(5).trim();
                    }
                  }

                  if (event === "live_url") {
                    // Forward the live browser URL the instant Composio provisions it.
                    try {
                      const parsed = JSON.parse(data) as { url?: string };
                      if (parsed.url) {
                        dataStream.write({
                          type: "data-agent-session-liveurl",
                          data: { agentId, liveUrl: parsed.url },
                        });
                      }
                    } catch {
                      // Ignore malformed live_url frame.
                    }
                  } else if (event === "agent_step") {
                    try {
                      const parsed = JSON.parse(data) as {
                        step?: number;
                        goal?: string;
                        url?: string;
                        status?: string;
                      };
                      if (typeof parsed.step === "number") {
                        dataStream.write({
                          type: "data-agent-browser-step",
                          data: {
                            agentId,
                            step: parsed.step,
                            goal: parsed.goal ?? "",
                            url: parsed.url ?? "",
                            status: parsed.status ?? "running",
                          },
                        });
                      }
                    } catch {
                      // Ignore malformed agent_step frame.
                    }
                  } else if (event === "task_update") {
                    // Real browser metrics (Browserbase run finished): surface the
                    // actual duration/cost/bandwidth on the current agent step
                    // (data-stream-handler.tsx matches the same `sr-step-N` id the
                    // last data-agent-browser-step emitted — step=1 for a tool).
                    try {
                      const parsed = JSON.parse(data) as {
                        status?: string;
                        durationMs?: number;
                        costCents?: number;
                        proxyBytes?: number;
                        sessionId?: string;
                        contextId?: string;
                      };
                      if (parsed) {
                        dataStream.write({
                          type: "data-agent-task-update",
                          data: {
                            agentId,
                            taskId: "sr-step-1",
                            status: "completed",
                            durationMs: parsed.durationMs ?? 0,
                            costCents: parsed.costCents ?? 0,
                          },
                        });
                      }
                    } catch {
                      // Ignore malformed task_update frame.
                    }
                  } else if (event === "complete") {
                    try {
                      const parsed = JSON.parse(data) as {
                        reply?: string;
                        data?: Record<string, unknown> | null;
                      };
                      finalReply = parsed.reply ?? "";
                      finalData = parsed.data ?? null;
                    } catch {
                      // Ignore malformed complete frame.
                    }
                  }
                  // "conversation_start" / "progress" ignored: monitor is already
                  // open optimistically and progress isn't surfaced here.
                  sep = buffer.indexOf("\n\n");
                }
              }

              // 3) Real reply from backend (formatted registral markdown) — finalize
              //    the chat message immediately so the user can keep chatting.
              assistantText = finalReply;
              // A business error (e.g. BROWSER_ERROR) ships as `data.error` on
              // the complete frame. The reply text is already short (see
              // format_registro_response) and the raw detail must stay hidden,
              // so skip the verbose <details> JSON dump for error responses.
              const isError = Boolean(
                finalData && typeof finalData === "object" && finalData.error
              );
              if (!isError && finalData && typeof finalData === "object") {
                const { live_url: _omit, ...rest } = finalData as Record<
                  string,
                  unknown
                >;
                assistantText += `\n\n<details><summary>Datos</summary>\n\n\`\`\`json\n${JSON.stringify(rest, null, 2)}\n\`\`\`\n\n</details>`;
              }
              for (const chunk of chunkText(assistantText)) {
                dataStream.write({
                  type: "text-delta",
                  id: textPartId,
                  delta: chunk,
                });
              }
              dataStream.write({ type: "text-end", id: textPartId });

              if (isError) {
                // Business failure: do NOT keep the 10-minute window open —
                // close the session in an ERROR state immediately so the
                // sidebar shows the error instead of a ticking clock.
                dataStream.write({
                  type: "data-agent-session-complete",
                  data: { agentId, durationMs: 0, status: "error" },
                });
              } else {
                // Keep the live browser + monitor open for the tool's window
                // (from command fire), even though the backend finished
                // earlier. Only then mark tasks completed + close the session.
                const remainingMs = Math.max(
                  0,
                  windowMs - (Date.now() - startedAt)
                );
                if (remainingMs > 0) {
                  await new Promise((resolve) =>
                    setTimeout(resolve, remainingMs)
                  );
                }
                dataStream.write({
                  type: "data-agent-session-complete",
                  data: { agentId, durationMs: 0 },
                });
              }
            } catch (err) {
              // Run failed (timeout / backend error). Close the monitor + finalize.
              dataStream.write({
                type: "data-agent-session-complete",
                data: { agentId, durationMs: 0 },
              });
              const { detail } = describeBackendError(err);
              assistantText = `No pude completar la consulta: ${detail}`;
              for (const chunk of chunkText(assistantText)) {
                dataStream.write({
                  type: "text-delta",
                  id: textPartId,
                  delta: chunk,
                });
              }
              dataStream.write({ type: "text-end", id: textPartId });
            }
          } else {
            // The backend is the sole intent router: forward every message,
            // even ones without a CUIT — it answers with its help/UNKNOWN
            // reply. Deterministic engine tools (consultaarca /
            // calendariovencimientosarca) land here too: no agent monitor,
            // and their formatted reply already shows everything, so we skip
            // the raw JSON dump for them.
            const history = buildHistory(uiMessages as ClientUIMessage[]);
            // Deterministic engines (consulta arca, calendariovencimientosarca)
            // go through the non-stream path: emit the title immediately as a
            // marker so the sidebar revalidates and shows the chat as soon as
            // the backend persists it running at dispatch. The finally block
            // still PATCHes the friendly title once the run completes.
            if (uiMessages.length === 1 && cuit) {
              dataStream.write({
                type: "data-chat-title",
                data: buildChatTitle(cuit, new Date()),
              });
            }
            const res = await callBackend<ChatResponse>("/v1/chat/message", {
              method: "POST",
              body: {
                message: userText,
                conversation_id: id,
                history: history.length ? history : null,
                // The backend reports REQUIRE an active profile_id (400
                // REPORT_PROFILE_REQUIRED otherwise). Forward what the client
                // sent (camelCase → profile_id) and never drop it.
                profile_id: activeProfileId ?? undefined,
                tools: hasToolCommand ? toolKeys : undefined,
              },
              timeoutMs: 60_000,
            });

            assistantText = res.reply;
            if (
              res.data &&
              typeof res.data === "object" &&
              !suppressJsonDump
            ) {
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
            dataStream.write({ type: "text-end", id: textPartId });
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
          dataStream.write({ type: "text-end", id: textPartId });
        } finally {
          // Title at stream start (tool branch) already emitted + PATCHed the
          // title — never double-patch for the same conversation. Non-tool
          // chats (titleSent stays false) behave exactly like before.
          if (!titleSent && uiMessages.length === 1) {
            const title = buildChatTitle(cuit, new Date());
            dataStream.write({ type: "data-chat-title", data: title });
            // The backend persisted the conversation itself (user + assistant,
            // status done). Only the final title is BFF-owned: PATCH it so the
            // sidebar shows the friendly title. PATCH never creates (CD-2) —
            // a deleted chat yields `{ok:false}` and the title is not saved.
            try {
              const { ok } = await patchConversationTitle(id, title);
              if (!ok) {
                console.error(
                  "Chat title not saved: conversation missing or deleted:",
                  id
                );
              }
            } catch (titleErr) {
              console.error("Failed to save chat title:", titleErr);
            }
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

export async function DELETE(request: Request) {
  const { searchParams } = new URL(request.url);
  const chatId = searchParams.get("id");

  if (!chatId) {
    return new ChatbotError(
      "bad_request:api",
      "Parameter id is required."
    ).toResponse();
  }

  const { userId } = await auth();
  if (!userId) {
    return new ChatbotError("unauthorized:chat").toResponse();
  }

  try {
    const { deleted } = await deleteConversation(chatId);
    if (!deleted) {
      // CD-3 honest failure: the backend 404s missing, already-deleted, or
      // cross-tenant chats. Never swallow it as a successful no-op — the
      // client must keep the row and surface an error.
      return Response.json(buildDeleteChatResponse(false), { status: 404 });
    }
    return Response.json(buildDeleteChatResponse(true), { status: 200 });
  } catch (err) {
    const { detail } = describeBackendError(err);
    const code =
      err instanceof BackendError ? backendErrorToCode(err) : "offline:chat";
    return new ChatbotError(code, detail).toResponse();
  }
}
