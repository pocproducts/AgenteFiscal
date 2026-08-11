"use client";

import {
  Activity,
  BarChart,
  Bot,
  ChevronRight,
  CreditCard,
  Home,
  MessageSquareIcon,
  PanelLeftIcon,
  Server,
  Settings,
  SquarePlus,
  TrendingUp,
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
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useLanguage } from "@/lib/i18n";
import type { PanelUser } from "@/lib/shared/db-types";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../ui/collapsible";

import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

export function AppSidebar({ user }: { user: PanelUser | undefined }) {
  const { t } = useLanguage();
  const { setOpenMobile, toggleSidebar } = useSidebar();
  const pathname = usePathname();
  const nav = t.panel.sidebar;

  const isHome = pathname === "/chat";
  const isAgentSessionsNew = pathname === "/agent-sessions/new";
  const isAgentSessions = pathname === "/agent-sessions";
  const isOverview = pathname === "/analytics/overview";
  const isLlmGateway = pathname === "/analytics/llm-gateway";
  const isBilling = pathname === "/settings/billing";
  const isProfiles = pathname === "/settings/profiles";

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="pb-0 pt-3">
        <SidebarMenu>
          <SidebarMenuItem className="flex flex-row items-center justify-between">
            <div className="group/logo relative flex items-center justify-center">
              <SidebarMenuButton
                asChild
                className="size-8 !px-0 items-center justify-center group-data-[collapsible=icon]:group-hover/logo:opacity-0"
                isActive={isHome}
                tooltip={nav.chatbot}
              >
                <Link href="/chat" onClick={() => setOpenMobile(false)}>
                  <MessageSquareIcon className="size-4 text-sidebar-foreground/50" />
                </Link>
              </SidebarMenuButton>
              <Tooltip>
                <TooltipTrigger asChild>
                  <SidebarMenuButton
                    className="pointer-events-none absolute inset-0 size-8 opacity-0 group-data-[collapsible=icon]:pointer-events-auto group-data-[collapsible=icon]:group-hover/logo:opacity-100"
                    onClick={() => toggleSidebar()}
                  >
                    <PanelLeftIcon className="size-4" />
                  </SidebarMenuButton>
                </TooltipTrigger>
                <TooltipContent className="hidden md:block" side="right">
                  {nav.openSidebar}
                </TooltipContent>
              </Tooltip>
            </div>
            <div className="group-data-[collapsible=icon]:hidden">
              <SidebarTrigger className="text-sidebar-foreground/60 transition-colors duration-150 hover:text-sidebar-foreground" />
            </div>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="pt-1">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={isHome} tooltip={nav.home}>
                  <Link href="/chat" onClick={() => setOpenMobile(false)}>
                    <Home className="size-4" />
                    <span>{nav.home}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>

              <Collapsible className="group/collapsible" defaultOpen>
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      isActive={isAgentSessions || isAgentSessionsNew}
                      tooltip={nav.agents}
                    >
                      <Bot className="size-4" />
                      <span>{nav.agents}</span>
                      <ChevronRight className="ml-auto size-4 transition-transform group-data-[state=open]/collapsible:rotate-90" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton
                          asChild
                          isActive={isAgentSessionsNew}
                        >
                          <Link
                            href="/agent-sessions/new"
                            onClick={() => setOpenMobile(false)}
                          >
                            <SquarePlus className="size-4" />
                            <span>{nav.newAgent}</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton
                          asChild
                          isActive={isAgentSessions}
                        >
                          <Link
                            href="/agent-sessions"
                            onClick={() => setOpenMobile(false)}
                          >
                            <Activity className="size-4" />
                            <span>{nav.agentSessions}</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup className="pt-0">
          <SidebarGroupContent>
            <SidebarMenu>
              <Collapsible className="group/collapsible" defaultOpen>
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      isActive={isOverview || isLlmGateway}
                      tooltip={nav.analytics}
                    >
                      <BarChart className="size-4" />
                      <span>{nav.analytics}</span>
                      <ChevronRight className="ml-auto size-4 transition-transform group-data-[state=open]/collapsible:rotate-90" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton asChild isActive={isOverview}>
                          <Link
                            href="/analytics/overview"
                            onClick={() => setOpenMobile(false)}
                          >
                            <TrendingUp className="size-4" />
                            <span>{nav.overview}</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton asChild isActive={isLlmGateway}>
                          <Link
                            href="/analytics/llm-gateway"
                            onClick={() => setOpenMobile(false)}
                          >
                            <Server className="size-4" />
                            <span>{nav.llmGateway}</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>

              <Collapsible className="group/collapsible" defaultOpen>
                <SidebarMenuItem>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      isActive={isBilling || isProfiles}
                      tooltip={nav.settings}
                    >
                      <Settings className="size-4" />
                      <span>{nav.settings}</span>
                      <ChevronRight className="ml-auto size-4 transition-transform group-data-[state=open]/collapsible:rotate-90" />
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton asChild isActive={isBilling}>
                          <Link
                            href="/settings/billing"
                            onClick={() => setOpenMobile(false)}
                          >
                            <CreditCard className="size-4" />
                            <span>{nav.billing}</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                      <SidebarMenuSubItem>
                        <SidebarMenuSubButton asChild isActive={isProfiles}>
                          <Link
                            href="/settings/profiles"
                            onClick={() => setOpenMobile(false)}
                          >
                            <Users className="size-4" />
                            <span>{nav.profiles}</span>
                          </Link>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </SidebarMenuItem>
              </Collapsible>
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
