import { Briefcase } from "lucide-react";
import { cookies } from "next/headers";
import { getDictionary } from "@/lib/i18n/server";

export default async function WorkspacesSettingsPage() {
  const cookieStore = await cookies();
  const locale = cookieStore.get("optimus-lang")?.value === "en" ? "en" : "es";
  const t = getDictionary(locale);
  const ws = t.panel.pages.workspaces;

  return (
    <div className="flex flex-1 flex-col h-full bg-background/50">
      <div className="flex flex-col items-center justify-center border-b border-border/40 px-6 py-8 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 mb-3">
          <Briefcase className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          {ws.title}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">{ws.description}</p>
      </div>
      <div className="flex-1 p-6">
        <div className="text-muted-foreground text-sm">{ws.empty}</div>
      </div>
    </div>
  );
}
