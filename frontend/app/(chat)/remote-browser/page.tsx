import { Globe } from "lucide-react";
import { cookies } from "next/headers";
import { RemoteBrowserTable } from "@/components/remote-browser/remote-browser-table";
import { getDictionary } from "@/lib/i18n/server";

export default async function RemoteBrowserPage() {
  const cookieStore = await cookies();
  const locale = cookieStore.get("optimus-lang")?.value === "en" ? "en" : "es";
  const t = getDictionary(locale);
  const dict = t.panel.pages.remoteBrowser;

  return (
    <div className="flex flex-1 flex-col h-full bg-background/50">
      <div className="flex items-center gap-4 border-b border-border/40 px-6 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
          <Globe className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">
            {dict.title}
          </h1>
          <p className="text-sm text-muted-foreground">{dict.description}</p>
        </div>
      </div>

      <div className="flex-1 p-6">
        <RemoteBrowserTable dict={dict} />
      </div>
    </div>
  );
}
