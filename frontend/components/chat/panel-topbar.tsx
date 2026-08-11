"use client";

import { OrganizationSwitcherWidget } from "@/components/auth/clerk-widgets";
import { PlanBadgeWidget } from "@/components/billing/plan-badge-widget";
import { TokenBalanceWidget } from "@/components/billing/token-balance-widget";
import { useLanguage } from "@/lib/i18n";

const organizationSwitcherAppearance = {
  variables: {
    colorPrimary: "hsl(var(--primary))",
    colorBackground: "hsl(var(--popover))",
    colorText: "hsl(var(--foreground))",
    colorTextSecondary: "hsl(var(--muted-foreground))",
    colorInputBackground: "hsl(var(--input))",
    colorInputText: "hsl(var(--foreground))",
    borderRadius: "var(--radius)",
    fontSize: "13px",
  },
  elements: {
    organizationSwitcherTrigger:
      "rounded-lg border border-border bg-card px-2 h-8 text-sm text-foreground hover:bg-accent",
    organizationPreviewMainIdentifier: "text-foreground",
    organizationSwitcherPopoverCard:
      "bg-popover border border-border shadow-md",
    organizationSwitcherPopoverActionButton: "text-foreground",
  },
} as const;

/**
 * Account-level bar: tenant switcher, token balance, contracted plan.
 * Lives in the panel layout (not a page-specific header) so it's visible on
 * every route — dashboard, agents, analytics, settings, and inside chats.
 */
export function PanelTopbar() {
  const { t } = useLanguage();
  const billingDict = t.panel.billingWidgets;

  return (
    <header className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-2 border-b border-border/40 bg-sidebar px-3">
      <OrganizationSwitcherWidget
        afterCreateOrganizationUrl="/chat"
        afterSelectOrganizationUrl="/chat"
        appearance={organizationSwitcherAppearance}
        hidePersonal
      />

      <div className="ml-auto flex items-center gap-2">
        <TokenBalanceWidget dict={billingDict} />
        <PlanBadgeWidget dict={billingDict} />
      </div>
    </header>
  );
}
