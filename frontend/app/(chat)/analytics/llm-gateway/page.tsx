import { Server } from "lucide-react";
import { cookies } from "next/headers";
import { LlmGatewayPanel } from "@/components/analytics/llm-gateway-panel";
import { getDictionary } from "@/lib/i18n/server";

export default async function LLMGatewayPage() {
  const cookieStore = await cookies();
  const locale = cookieStore.get("optimus-lang")?.value === "en" ? "en" : "es";
  const t = getDictionary(locale);
  const gw = t.panel.pages.analytics.llmGateway;

  return (
    <div className="flex flex-1 flex-col h-full bg-background/50">
      <div className="flex items-center gap-4 border-b border-border/40 px-6 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
          <Server className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">
            {gw.title}
          </h1>
          <p className="text-sm text-muted-foreground">{gw.description}</p>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        <LlmGatewayPanel />
      </div>
    </div>
  );
}
