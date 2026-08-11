"use client";

import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { ChatShell } from "@/components/chat/shell";
import { ActiveChatProvider } from "@/hooks/use-active-chat";

export function ChatLayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Bare "/chat" is the dashboard (see app/(chat)/chat/page.tsx) — only an
  // actual conversation id mounts the chat shell.
  const isChatRoute = pathname.startsWith("/chat/");

  if (!isChatRoute) {
    return <>{children}</>;
  }

  return (
    <>
      <Suspense fallback={<div className="flex h-dvh" />}>
        <ActiveChatProvider>
          <ChatShell />
        </ActiveChatProvider>
      </Suspense>
      {children}
    </>
  );
}
