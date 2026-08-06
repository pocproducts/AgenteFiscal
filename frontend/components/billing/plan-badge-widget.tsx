"use client";

import { Sparkles } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { useBilling } from "@/hooks/use-billing";

interface PlanBadgeDict {
  planLabel: string;
  planHoverCta: string;
}

export function PlanBadgeWidget({ dict }: { dict: PlanBadgeDict }) {
  const { currentPlan } = useBilling();

  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <Badge
          className="h-8 cursor-pointer gap-1 rounded-lg px-2.5"
          variant="outline"
        >
          <Sparkles className="size-3.5 text-muted-foreground" />
          {dict.planLabel}: {currentPlan ?? "—"}
        </Badge>
      </HoverCardTrigger>
      <HoverCardContent align="end" className="w-56">
        <p className="text-sm font-semibold text-foreground">
          {currentPlan ?? "—"}
        </p>
        <Link
          className="mt-2 inline-block text-xs font-medium text-primary hover:underline"
          href="/settings/billing"
        >
          {dict.planHoverCta}
        </Link>
      </HoverCardContent>
    </HoverCard>
  );
}
