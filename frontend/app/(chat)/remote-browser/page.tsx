import {
  Activity,
  Bot,
  Clock,
  Code,
  DollarSign,
  Globe,
  Hash,
  MapPin,
  Wifi,
} from "lucide-react";
import { cookies } from "next/headers";
import { getDictionary } from "@/lib/i18n/server";

const DUMMY_BROWSERS = [
  {
    browser: "Chromium 124",
    cdpUrl: "ws://127.0.0.1:9222/devtools/browser/xyz",
    live: true,
    profileId: "—",
    agent: "sess_x192837",
    region: "us-east-1",
    startedAt: "2026-07-06 10:14",
    duration: "45s",
    cost: "$0.02",
  },
  {
    browser: "Firefox 120",
    cdpUrl: "ws://127.0.0.1:9222/devtools/browser/abc",
    live: false,
    profileId: "—",
    agent: "sess_y827364",
    region: "eu-west-1",
    startedAt: "2026-07-06 10:20",
    duration: "12s",
    cost: "$0.01",
  },
];

export default async function RemoteBrowserPage() {
  const cookieStore = await cookies();
  const locale =
    cookieStore.get("optimus-lang")?.value === "en" ? "en" : "es";
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
        <div className="rounded-xl border border-border/50 bg-background/50 shadow-sm overflow-hidden">
          <table className="w-full text-left text-sm whitespace-nowrap">
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <Globe className="size-4" /> {dict.browser}
                  </div>
                </th>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <Code className="size-4" /> {dict.cdpUrl}
                  </div>
                </th>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <Wifi className="size-4" /> {dict.live}
                  </div>
                </th>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <Hash className="size-4" /> {dict.profileId}
                  </div>
                </th>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <Bot className="size-4" /> {dict.agent}
                  </div>
                </th>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <MapPin className="size-4" /> {dict.region}
                  </div>
                </th>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <Clock className="size-4" /> {dict.startedAt}
                  </div>
                </th>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <Activity className="size-4" /> {dict.duration}
                  </div>
                </th>
                <th className="px-4 py-3 font-medium">
                  <div className="flex items-center gap-2">
                    <DollarSign className="size-4" /> {dict.cost}
                  </div>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {DUMMY_BROWSERS.map((b, i) => (
                <tr className="hover:bg-muted/20 transition-colors" key={i}>
                  <td className="px-4 py-3 text-foreground font-medium">
                    {b.browser}
                  </td>
                  <td
                    className="px-4 py-3 font-mono text-[11px] truncate max-w-[150px]"
                    title={b.cdpUrl}
                  >
                    {b.cdpUrl}
                  </td>
                  <td className="px-4 py-3">
                    {b.live ? (
                      <span className="flex w-fit items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-emerald-600">
                        <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
                        {dict.livestatus}
                      </span>
                    ) : (
                      <span className="flex w-fit items-center gap-1.5 rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold tracking-wide text-muted-foreground">
                        <span className="size-1.5 rounded-full bg-muted-foreground" />
                        {dict.offlinestatus}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{b.profileId}</td>
                  <td className="px-4 py-3 font-mono text-xs">{b.agent}</td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {b.region}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {b.startedAt}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {b.duration}
                  </td>
                  <td className="px-4 py-3 text-emerald-500 font-medium">
                    {b.cost}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {DUMMY_BROWSERS.length === 0 && (
            <div className="p-8 text-center text-muted-foreground">
              {dict.empty}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
