"use client";

import type { UseChatHelpers } from "@ai-sdk/react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { usePathname, useSearchParams } from "next/navigation";
import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import useSWR, { useSWRConfig } from "swr";
import { unstable_serialize } from "swr/infinite";
import { useDataStream } from "@/components/chat/data-stream-provider";
import { getChatHistoryPaginationKey } from "@/components/chat/sidebar-history";
import { toast } from "@/components/chat/toast";
import type { VisibilityType } from "@/components/chat/visibility-selector";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { useAutoResume } from "@/hooks/use-auto-resume";
import { DEFAULT_CHAT_MODEL } from "@/lib/ai/models";
import type { AgentSessionSnapshot } from "@/lib/ai/tools/agent-execution";
import type { Vote } from "@/lib/db/schema";
import { ChatbotError } from "@/lib/errors";
import type { ChatMessage } from "@/lib/types";
import { fetcher, fetchWithErrorHandlers, generateUUID } from "@/lib/utils";

type ActiveChatContextValue = {
  chatId: string;
  messages: ChatMessage[];
  setMessages: UseChatHelpers<ChatMessage>["setMessages"];
  sendMessage: UseChatHelpers<ChatMessage>["sendMessage"];
  status: UseChatHelpers<ChatMessage>["status"];
  stop: UseChatHelpers<ChatMessage>["stop"];
  regenerate: UseChatHelpers<ChatMessage>["regenerate"];
  addToolApprovalResponse: UseChatHelpers<ChatMessage>["addToolApprovalResponse"];
  input: string;
  setInput: Dispatch<SetStateAction<string>>;
  visibilityType: VisibilityType;
  isReadonly: boolean;
  isLoading: boolean;
  /** True while a launch's `?query=` is queued but not sent yet — messages
   * being empty during this window doesn't mean the chat is actually empty. */
  hasPendingLaunch: boolean;
  votes: Vote[] | undefined;
  currentModelId: string;
  setCurrentModelId: (id: string) => void;
  showCreditCardAlert: boolean;
  setShowCreditCardAlert: Dispatch<SetStateAction<boolean>>;
};

const ActiveChatContext = createContext<ActiveChatContextValue | null>(null);

function extractChatId(pathname: string): string | null {
  const match = pathname.match(/\/chat\/([^/]+)/);
  return match ? match[1] : null;
}

export function ActiveChatProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // Next's router-synced search params — reading window.location.search
  // directly in a lazy useState initializer is unreliable here: this
  // provider mounts fresh (inside a Suspense boundary) the moment a
  // client-side navigation lands on /chat/[id], and the raw browser URL can
  // still be racing that transition at the instant the initializer runs.
  const searchParams = useSearchParams();
  const { setDataStream } = useDataStream();
  const { mutate } = useSWRConfig();
  const { hydrate } = useAgentSidebar();

  const chatIdFromUrl = extractChatId(pathname);
  // A chat launched with a pending `?query=` (e.g. from AgentComposer) already
  // has its id in the URL, but the row doesn't exist server-side until that
  // query is actually sent — treat it as "new" until then, so we don't fetch
  // /api/messages (or try to resume a stream) for a chat that isn't there yet.
  const [pendingLaunchQuery, setPendingLaunchQuery] = useState<string | null>(
    () => searchParams.get("query")
  );
  const isNewChat = !chatIdFromUrl || pendingLaunchQuery !== null;
  const newChatIdRef = useRef(generateUUID());
  const prevPathnameRef = useRef(pathname);

  if (isNewChat && prevPathnameRef.current !== pathname) {
    newChatIdRef.current = generateUUID();
  }
  prevPathnameRef.current = pathname;

  const chatId = chatIdFromUrl ?? newChatIdRef.current;

  const [currentModelId, setCurrentModelId] = useState(DEFAULT_CHAT_MODEL);
  const currentModelIdRef = useRef(currentModelId);
  useEffect(() => {
    currentModelIdRef.current = currentModelId;
  }, [currentModelId]);

  const [input, setInput] = useState("");
  const [showCreditCardAlert, setShowCreditCardAlert] = useState(false);

  // Revalidates the sidebar history list the first time a chunk streams in
  // for a given chat, so a freshly-launched chat (created "running" server-
  // side on its first message) shows up right away instead of only once the
  // whole tool sequence finishes (onFinish, below).
  const historyRevalidatedForChatRef = useRef<string | null>(null);

  // Tracks the chat whose report was produced by a live stream in this
  // session. A launch captures a stale /api/messages snapshot mid-flight
  // (often containing only the user message), and the hydration effect below
  // would apply that snapshot once the stream finishes — erasing the executed
  // tools and the report from the UI. The live report is authoritative while
  // this chat is open; a reopen (navigate away and back, or from history)
  // does a clean fetch of the persisted copy.
  const streamedLiveForChatRef = useRef<string | null>(null);

  const {
    data: chatData,
    isLoading,
    mutate: mutateChatData,
  } = useSWR(
    isNewChat
      ? null
      : `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/messages?chatId=${chatId}`,
    fetcher,
    { revalidateOnFocus: false }
  );

  const initialMessages: ChatMessage[] = isNewChat
    ? []
    : (chatData?.messages ?? []);
  const visibility: VisibilityType = isNewChat
    ? "private"
    : (chatData?.visibility ?? "private");

  const {
    messages,
    setMessages,
    sendMessage,
    status,
    stop,
    regenerate,
    addToolApprovalResponse,
  } = useChat<ChatMessage>({
    id: chatId,
    messages: initialMessages,
    generateId: generateUUID,
    sendAutomaticallyWhen: ({ messages: currentMessages }) => {
      const lastMessage = currentMessages.at(-1);
      return (
        lastMessage?.parts?.some(
          (part) =>
            "state" in part &&
            part.state === "approval-responded" &&
            "approval" in part &&
            (part.approval as { approved?: boolean })?.approved === true
        ) ?? false
      );
    },
    transport: new DefaultChatTransport({
      api: `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/chat`,
      fetch: fetchWithErrorHandlers,
      prepareSendMessagesRequest(request) {
        const lastMessage = request.messages.at(-1);
        const isToolApprovalContinuation =
          lastMessage?.role !== "user" ||
          request.messages.some((msg) =>
            msg.parts?.some((part) => {
              const state = (part as { state?: string }).state;
              return (
                state === "approval-responded" || state === "output-denied"
              );
            })
          );

        let activeProfileId: string | null = null;
        if (typeof window !== "undefined") {
          try {
            const rawStoredProfileId =
              localStorage.getItem("active-profile-id");
            if (rawStoredProfileId) {
              const parsed = JSON.parse(rawStoredProfileId);
              if (typeof parsed === "string" && parsed.length > 0) {
                activeProfileId = parsed;
              }
            }
          } catch {
            // Ignore malformed stored profile IDs — fall back gracefully.
          }
        }

        return {
          body: {
            id: request.id,
            ...(isToolApprovalContinuation
              ? { messages: request.messages }
              : { message: lastMessage }),
            selectedChatModel: currentModelIdRef.current,
            selectedVisibilityType: visibility,
            profileId: activeProfileId,
            ...request.body,
          },
        };
      },
    }),
    onData: (dataPart) => {
      setDataStream((ds) => (ds ? [...ds, dataPart] : []));
      streamedLiveForChatRef.current = chatId;
      if (historyRevalidatedForChatRef.current !== chatId) {
        historyRevalidatedForChatRef.current = chatId;
        mutate(unstable_serialize(getChatHistoryPaginationKey));
      }
    },
    onFinish: () => {
      mutate(unstable_serialize(getChatHistoryPaginationKey));
    },
    onError: (error) => {
      if (error.message?.includes("AI Gateway requires a valid credit card")) {
        setShowCreditCardAlert(true);
      } else if (error instanceof ChatbotError) {
        toast({ type: "error", description: error.message });
      } else {
        toast({
          type: "error",
          description: error.message || "Oops, an error occurred!",
        });
      }
    },
  });

  // Hydrate messages from the persisted chat whenever fresh chatData arrives.
  // Navigation to an already-cached chat must refetch: otherwise SWR serves
  // the stale empty response captured before the report was saved, and the
  // empty state shows instead of the persisted conversation.
  const lastRequestedChatRef = useRef<string | null>(null);
  useEffect(() => {
    if (isNewChat) {
      return;
    }
    if (lastRequestedChatRef.current !== chatId) {
      lastRequestedChatRef.current = chatId;
      mutateChatData().catch(() => {
        // Ignore refetch failures — the active chat state is already optimistic.
      });
    }
  }, [chatId, isNewChat, mutateChatData]);

  useEffect(() => {
    if (isNewChat || !chatData?.messages) {
      return;
    }
    // Never clobber an in-flight stream (the live report is authoritative).
    if (status === "streaming" || status === "submitted") {
      return;
    }
    // A report produced by a live stream in this session stays on screen when
    // the stream finishes: applying the mid-flight /api/messages snapshot
    // (captured with only the user message) would erase the executed tools.
    // The persisted assistant report is fetched cleanly on the next open.
    if (streamedLiveForChatRef.current !== chatId) {
      setMessages(chatData.messages);
    }
  }, [chatData?.messages, isNewChat, status, setMessages, chatId]);

  // Hydrate the agent monitor from persisted per-chat activity on load. Guarded
  // by a set-of-hydrated-ids so re-renders / SWR revalidation don't double-run
  // or clobber live sessions.
  const hydratedChatIds = useRef(new Set<string>());
  useEffect(() => {
    if (isNewChat || !chatData?.activity?.length) {
      return;
    }
    if (hydratedChatIds.current.has(chatId)) {
      return;
    }
    hydratedChatIds.current.add(chatId);
    hydrate(chatId, chatData.activity as AgentSessionSnapshot[]);
  }, [chatId, chatData?.activity, hydrate, isNewChat]);

  const prevChatIdRef = useRef(chatId);
  useEffect(() => {
    if (prevChatIdRef.current !== chatId) {
      prevChatIdRef.current = chatId;
      if (isNewChat) {
        setMessages([]);
      }
    }
  }, [chatId, isNewChat, setMessages]);

  useEffect(() => {
    if (chatData && !isNewChat) {
      const cookieModel = document.cookie
        .split("; ")
        .find((row) => row.startsWith("chat-model="))
        ?.split("=")[1];
      if (cookieModel) {
        setCurrentModelId(decodeURIComponent(cookieModel));
      }
    }
  }, [chatData, isNewChat]);

  // Idempotency guard for ?query= launches. React StrictMode double-invokes
  // effects in dev, and a double sendMessage() would fire the whole fiscal
  // pipeline twice (duplicated tools, duplicated agent sessions, duplicated
  // persisted messages). Track the exact query already launched so the second
  // effect pass is a no-op.
  const launchedQueryRef = useRef<string | null>(null);
  useEffect(() => {
    if (!pendingLaunchQuery) {
      return;
    }
    if (launchedQueryRef.current === pendingLaunchQuery) {
      return;
    }
    launchedQueryRef.current = pendingLaunchQuery;
    window.history.replaceState(
      {},
      "",
      `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/chat/${chatId}`
    );
    sendMessage({
      role: "user" as const,
      parts: [{ type: "text", text: pendingLaunchQuery }],
    });
    setPendingLaunchQuery(null);
  }, [sendMessage, chatId, pendingLaunchQuery]);

  useAutoResume({
    initialMessages,
    setMessages,
  });

  const isReadonly = isNewChat ? false : (chatData?.isReadonly ?? false);

  const { data: votes } = useSWR<Vote[]>(
    !isReadonly && messages.length >= 2
      ? `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api/vote?chatId=${chatId}`
      : null,
    fetcher,
    { revalidateOnFocus: false }
  );

  const value = useMemo<ActiveChatContextValue>(
    () => ({
      chatId,
      messages,
      setMessages,
      sendMessage,
      status,
      stop,
      regenerate,
      addToolApprovalResponse,
      input,
      setInput,
      visibilityType: visibility,
      isReadonly,
      isLoading: !isNewChat && isLoading,
      hasPendingLaunch: pendingLaunchQuery !== null,
      votes,
      currentModelId,
      setCurrentModelId,
      showCreditCardAlert,
      setShowCreditCardAlert,
    }),
    [
      chatId,
      messages,
      setMessages,
      sendMessage,
      status,
      stop,
      regenerate,
      addToolApprovalResponse,
      input,
      visibility,
      isReadonly,
      isNewChat,
      isLoading,
      pendingLaunchQuery,
      votes,
      currentModelId,
      showCreditCardAlert,
    ]
  );

  return (
    <ActiveChatContext.Provider value={value}>
      {children}
    </ActiveChatContext.Provider>
  );
}

export function useActiveChat() {
  const context = useContext(ActiveChatContext);
  if (!context) {
    throw new Error("useActiveChat must be used within ActiveChatProvider");
  }
  return context;
}
