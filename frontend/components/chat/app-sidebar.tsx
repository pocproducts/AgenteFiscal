"use client";

import {
  Activity,
  CreditCard,
  Home,
  PanelLeftIcon,
  SquarePlus,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SidebarHistory } from "@/components/chat/sidebar-history";
import { SidebarUserNav } from "@/components/chat/sidebar-user-nav";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useLanguage } from "@/lib/i18n";
import type { PanelUser } from "@/lib/shared/db-types";

export function AppSidebar({ user }: { user: PanelUser | undefined }) {
  const { t } = useLanguage();
  const { setOpenMobile, toggleSidebar } = useSidebar();
  const pathname = usePathname();
  const nav = t.panel.sidebar;

  const isHome = pathname === "/chat";
  const isAgentSessionsNew = pathname === "/agent-sessions/new";
  const isAgentSessions = pathname === "/agent-sessions";
  const isBilling = pathname === "/settings/billing";
  const isProfiles = pathname === "/settings/profiles";

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="pb-0 pt-3">
        <SidebarMenu>
          <SidebarMenuItem className="flex flex-row items-center justify-between">
            <SidebarMenuButton
              className="size-8"
              onClick={() => toggleSidebar()}
              tooltip={nav.openSidebar}
            >
              <PanelLeftIcon className="size-4" />
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="pt-1">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  asChild
                  size="sm"
                  isActive={isAgentSessionsNew}
                  tooltip={nav.newAgent}
                  className="w-fit rounded-full bg-[oklch(0.12_0_0)] text-white! hover:bg-[oklch(0.2_0_0)]"
                >
                  <Link href="/agent-sessions/new" onClick={() => setOpenMobile(false)}>
                    <SquarePlus className="size-4" />
                    <span>{nav.newAgent}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isHome} tooltip={nav.home}>
                  <Link href="/chat" onClick={() => setOpenMobile(false)}>
                    <Home className="size-4" />
                    <span>{nav.home}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isAgentSessions} tooltip={nav.agentSessions}>
                  <Link href="/agent-sessions" onClick={() => setOpenMobile(false)}>
                    <Activity className="size-4" />
                    <span>{nav.agentSessions}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isProfiles} tooltip={nav.profiles}>
                  <Link href="/settings/profiles" onClick={() => setOpenMobile(false)}>
                    <Users className="size-4" />
                    <span>{nav.profiles}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>

              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isBilling} tooltip={nav.billing}>
                  <Link href="/settings/billing" onClick={() => setOpenMobile(false)}>
                    <CreditCard className="size-4" />
                    <span>{nav.billing}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarHistory user={user} />
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border pt-2 pb-3">
        {user && <SidebarUserNav user={user} />}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
