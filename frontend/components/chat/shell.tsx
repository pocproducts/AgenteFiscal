"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useActiveChat } from "@/hooks/use-active-chat";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import {
  initialArtifactData,
  useArtifact,
  useArtifactSelector,
} from "@/hooks/use-artifact";
import { useLanguage } from "@/lib/i18n";
import type { Attachment, ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AgentSidebar } from "./agent-sidebar";
import { Artifact } from "./artifact";
import { ChatHeader } from "./chat-header";
import { DataStreamHandler } from "./data-stream-handler";
import { Messages } from "./messages";
import { MultimodalInput } from "./multimodal-input";

export function ChatShell() {
  const {
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
    visibilityType,
    isReadonly,
    isLoading,
    hasPendingLaunch,
    votes,
    currentModelId,
    setCurrentModelId,
    showCreditCardAlert,
    setShowCreditCardAlert,
  } = useActiveChat();

  const [_editingMessage, setEditingMessage] = useState<ChatMessage | null>(
    null
  );
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const isArtifactVisible = useArtifactSelector((state) => state.isVisible);
  const { setArtifact } = useArtifact();
  const { isOpen: isAgentSidebarOpen, close: closeAgentSidebar } =
    useAgentSidebar();

  const stopRef = useRef(stop);
  stopRef.current = stop;
  const { t } = useLanguage();
  const shell = t.panel.chat.shell;

  const prevChatIdRef = useRef(chatId);
  useEffect(() => {
    if (prevChatIdRef.current !== chatId) {
      prevChatIdRef.current = chatId;
      stopRef.current();
      setArtifact(initialArtifactData);
      closeAgentSidebar();
      setEditingMessage(null);
      setAttachments([]);
    }
  }, [chatId, setArtifact, closeAgentSidebar]);

  useEffect(() => {
    if (isArtifactVisible && isAgentSidebarOpen) {
      closeAgentSidebar();
    }
  }, [isArtifactVisible, isAgentSidebarOpen, closeAgentSidebar]);

  return (
    <>
      <div className="flex h-[calc(100dvh-3rem)] w-full flex-row overflow-hidden">
        <div
          className={cn(
            "flex min-w-0 flex-col bg-sidebar transition-[width] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]",
            isArtifactVisible
              ? "w-[40%]"
              : isAgentSidebarOpen
                ? "w-[60%]"
                : "w-full"
          )}
        >
          <ChatHeader
            chatId={chatId}
            isReadonly={isReadonly}
            selectedVisibilityType={visibilityType}
          />

          <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-background md:rounded-tl-[12px] md:border-t md:border-l md:border-border/40">
            <Messages
              addToolApprovalResponse={addToolApprovalResponse}
              chatId={chatId}
              hasPendingLaunch={hasPendingLaunch}
              isArtifactVisible={isArtifactVisible || isAgentSidebarOpen}
              isLoading={isLoading}
              isReadonly={isReadonly}
              messages={messages}
              onEditMessage={(msg) => {
                const text = (msg.parts ?? [])
                  ?.filter((p) => p.type === "text")
                  .map((p) => p.text)
                  .join("");
                setInput(text ?? "");
                setEditingMessage(msg);
              }}
              regenerate={regenerate}
              setMessages={setMessages}
              status={status}
              votes={votes}
            />

            {messages.length > 0 && (
              <MultimodalInput
                attachments={attachments}
                chatId={chatId}
                input={input}
                isLoading={isLoading}
                messages={messages}
                onModelChange={setCurrentModelId}
                selectedModelId={currentModelId}
                selectedVisibilityType={visibilityType}
                sendMessage={sendMessage}
                setAttachments={setAttachments}
                setInput={setInput}
                setMessages={setMessages}
                status={status}
                stop={stop}
              />
            )}
          </div>
        </div>

        <Artifact
          sendMessage={sendMessage}
          setMessages={setMessages}
          status={status}
          stop={stop}
        />

        {isAgentSidebarOpen && !isArtifactVisible && <AgentSidebar />}
      </div>

      <DataStreamHandler />

      <AlertDialog
        onOpenChange={setShowCreditCardAlert}
        open={showCreditCardAlert}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{shell.activateTitle}</AlertDialogTitle>
            <AlertDialogDescription>
              {shell.activateDescriptionBefore}{" "}
              {process.env.NODE_ENV === "production"
                ? shell.activateDescriptionOwner
                : shell.activateDescriptionYou}{" "}
              {shell.activateDescriptionAfter}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{shell.cancel}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                window.open(
                  "https://vercel.com/d?to=%2F%5Bteam%5D%2F~%2Fai%3Fmodal%3Dadd-credit-card",
                  "_blank"
                );
                window.location.href = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/`;
              }}
            >
              {shell.activate}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
