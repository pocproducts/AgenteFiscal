import { auth, clerkClient } from "@clerk/nextjs/server";
import { cookies } from "next/headers";
import Script from "next/script";
import { Suspense } from "react";
import { Toaster } from "sonner";
import { AppSidebar } from "@/components/chat/app-sidebar";
import { ChatLayoutWrapper } from "@/components/chat/chat-layout-wrapper";
import { DataStreamProvider } from "@/components/chat/data-stream-provider";
import { PanelTopbar } from "@/components/chat/panel-topbar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import type { PanelUser } from "@/lib/shared/db-types";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Script
        src="https://cdn.jsdelivr.net/pyodide/v0.23.4/full/pyodide.js"
        strategy="lazyOnload"
      />
      <DataStreamProvider>
        <Suspense fallback={<div className="flex h-dvh bg-sidebar" />}>
          <SidebarShell>{children}</SidebarShell>
        </Suspense>
      </DataStreamProvider>
    </>
  );
}

async function SidebarShell({ children }: { children: React.ReactNode }) {
  const [{ userId }, cookieStore] = await Promise.all([auth(), cookies()]);
  const isCollapsed = cookieStore.get("sidebar_state")?.value !== "true";

  let user: PanelUser | undefined;
  if (userId) {
    try {
      const client = await clerkClient();
      const clerkUser = await client.users.getUser(userId);
      user = {
        id: clerkUser.id,
        email: clerkUser.emailAddresses[0]?.emailAddress ?? null,
      };
    } catch {
      user = { id: userId };
    }
  }

  return (
    <SidebarProvider defaultOpen={!isCollapsed}>
      <AppSidebar user={user} />
      <SidebarInset>
        <Toaster
          position="top-center"
          theme="system"
          toastOptions={{
            className:
              "!bg-card !text-foreground !border-border/50 !shadow-[var(--shadow-float)]",
          }}
        />
        <PanelTopbar />
        <div className="flex min-h-0 flex-1 flex-col">
          <ChatLayoutWrapper>{children}</ChatLayoutWrapper>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
