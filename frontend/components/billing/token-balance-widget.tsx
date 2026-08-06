"use client";

import { Coins } from "lucide-react";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { useBilling } from "@/hooks/use-billing";

interface TokenBalanceDict {
  tokensLabel: string;
  tokensHoverTitle: string;
  tokensHoverDescription: string;
}

export function TokenBalanceWidget({ dict }: { dict: TokenBalanceDict }) {
  const { tokenBalance } = useBilling();

  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <button
          className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-2 text-xs font-medium text-foreground transition-colors hover:bg-accent"
          type="button"
        >
          <Coins className="size-3.5 text-muted-foreground" />
          <span className="font-mono">
            {tokenBalance?.toLocaleString("en-US") ?? "—"}
          </span>
          <span className="hidden text-muted-foreground sm:inline">
            {dict.tokensLabel}
          </span>
        </button>
      </HoverCardTrigger>
      <HoverCardContent align="end" className="w-64">
        <p className="text-sm font-semibold text-foreground">
          {dict.tokensHoverTitle}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {dict.tokensHoverDescription}
        </p>
      </HoverCardContent>
    </HoverCard>
  );
}
