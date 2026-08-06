"use client";

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
import { Skeleton } from "@/components/ui/skeleton";
import { useRemoteBrowsers } from "@/hooks/use-remote-browsers";

interface RemoteBrowserDict {
  browser: string;
  cdpUrl: string;
  live: string;
  profileId: string;
  agent: string;
  region: string;
  startedAt: string;
  duration: string;
  cost: string;
  livestatus: string;
  offlinestatus: string;
  empty: string;
}

const TH_CLASS = "px-4 py-3 font-medium";
const COLUMNS = 9;

export function RemoteBrowserTable({ dict }: { dict: RemoteBrowserDict }) {
  const { data } = useRemoteBrowsers();

  return (
    <div className="rounded-xl border border-border/50 bg-background/50 shadow-sm overflow-hidden">
      <table className="w-full text-left text-sm whitespace-nowrap">
        <thead className="bg-muted/30 text-muted-foreground">
          <tr>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <Globe className="size-4" /> {dict.browser}
              </div>
            </th>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <Code className="size-4" /> {dict.cdpUrl}
              </div>
            </th>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <Wifi className="size-4" /> {dict.live}
              </div>
            </th>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <Hash className="size-4" /> {dict.profileId}
              </div>
            </th>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <Bot className="size-4" /> {dict.agent}
              </div>
            </th>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <MapPin className="size-4" /> {dict.region}
              </div>
            </th>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <Clock className="size-4" /> {dict.startedAt}
              </div>
            </th>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <Activity className="size-4" /> {dict.duration}
              </div>
            </th>
            <th className={TH_CLASS}>
              <div className="flex items-center gap-2">
                <DollarSign className="size-4" /> {dict.cost}
              </div>
            </th>
          </tr>
        </thead>
        {data ? (
          data.length === 0 ? (
            <tbody>
              <tr>
                <td
                  className="p-8 text-center text-muted-foreground"
                  colSpan={COLUMNS}
                >
                  {dict.empty}
                </td>
              </tr>
            </tbody>
          ) : (
            <tbody className="divide-y divide-border/40">
              {data.map((b) => (
                <tr
                  className="hover:bg-muted/20 transition-colors"
                  key={`${b.agent}-${b.cdpUrl}`}
                >
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
          )
        ) : (
          <tbody className="divide-y divide-border/40">
            {[0, 1, 2, 3].map((n) => (
              <tr key={n}>
                <td className="px-4 py-3" colSpan={COLUMNS}>
                  <Skeleton className="h-5 w-full" />
                </td>
              </tr>
            ))}
          </tbody>
        )}
      </table>
    </div>
  );
}
