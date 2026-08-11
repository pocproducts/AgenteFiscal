"use client";

import type { UseChatHelpers } from "@ai-sdk/react";
import { useEffect } from "react";
import { useDataStream } from "@/components/chat/data-stream-provider";
import type { ChatMessage } from "@/lib/types";

export type UseAutoResumeParams = {
  initialMessages: ChatMessage[];
  setMessages: UseChatHelpers<ChatMessage>["setMessages"];
};

// Stream resumption (GET /api/chat/[id]/stream) has no backend here: the mock
// console runs each tool sequentially inside a single request/response and
// never persisted in-flight stream state (the resumable-stream/Redis piece
// was removed as an unused dep). Calling `resumeStream()` against a route
// that doesn't exist would 404 on every reload of a chat whose last message
// is from the user, so that call — and the now-unused `autoResume`/
// `resumeStream` params it needed — were dropped. Re-add them once a real
// backend persists resumable stream state.
export function useAutoResume({
  initialMessages,
  setMessages,
}: UseAutoResumeParams) {
  const { dataStream } = useDataStream();

  useEffect(() => {
    if (!dataStream) {
      return;
    }
    if (dataStream.length === 0) {
      return;
    }

    const dataPart = dataStream[0];

    if (dataPart.type === "data-appendMessage") {
      const message = JSON.parse(dataPart.data);
      setMessages([...initialMessages, message]);
    }
  }, [dataStream, initialMessages, setMessages]);
}
