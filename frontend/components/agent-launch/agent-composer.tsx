"use client";

import { Loader2, UserIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Suggestion } from "@/components/ai-elements/suggestion";
import { GreetingHeader } from "@/components/chat/greeting-header";
import {
  expandPlan,
  type SlashCommand,
  slashCommands,
} from "@/components/chat/slash-commands";
import { toast } from "@/components/chat/toast";
import { ProfileFormDialog } from "@/components/profiles/profile-form-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProfiles } from "@/hooks/use-profiles";
import { useLanguage } from "@/lib/i18n";
import { cn, generateUUID } from "@/lib/utils";

/** Sentinel select value that opens the shared "new profile" dialog. */
const NEW_PROFILE_VALUE = "__new_profile__";

/**
 * The "start a new report" layout — the only place that launches a fiscal
 * automation (a bare empty chat redirects here, see EmptyChatRedirect in
 * components/chat/messages.tsx). Picking a fiscal tool launches a new chat
 * that auto-sends "<cuit> /<tool> /<tool>…" via the `?query=` param
 * `use-active-chat` consumes on mount.
 *
 * The backend requires an ACTIVE profile to run reports (400 REPORT_PROFILE_REQUIRED
 * / 409 PROFILE_INACTIVE otherwise), so a profile selection lives next to the CUIT
 * input, is persisted via useProfiles (localStorage `active-profile-id`), and
 * travels with the launch URL as `?profile=<id>`.
 */
export function AgentComposer() {
  const router = useRouter();
  const { t } = useLanguage();
  const dict = t.panel.agentLaunch;
  const profileDict = t.panel.chat.profile;

  const { profiles, activeProfileId, setActiveProfileId } = useProfiles();
  const activeProfiles = profiles.filter((p) => p.status === "active");
  const hasProfile = activeProfileId !== "";

  const [cuit, setCuit] = useState("");
  const [selectedActions, setSelectedActions] = useState<Set<string>>(
    new Set()
  );
  const [isLaunching, setIsLaunching] = useState(false);
  const [isProfileDialogOpen, setIsProfileDialogOpen] = useState(false);
  const cuitValid = cuit.length === 11;
  const canRun = cuitValid && hasProfile;

  // Generated (and the /chat/[id] route prefetched) as soon as the user picks
  // a tool — not inside launch() — so the route's JS/RSC payload is already
  // warm by the time they hit "Next", instead of eating a multi-second
  // on-demand compile right after clicking it.
  const pendingChatIdRef = useRef<string | null>(null);

  const toggleAction = useCallback(
    (command: SlashCommand) => {
      if (pendingChatIdRef.current === null) {
        const chatId = generateUUID();
        pendingChatIdRef.current = chatId;
        router.prefetch(`/chat/${chatId}`);
      }
      setSelectedActions((prev) => {
        const next = new Set(prev);
        if (next.has(command.action)) {
          next.delete(command.action);
        } else {
          next.add(command.action);
        }
        return next;
      });
    },
    [router]
  );

  // Expanded plan for ALL selected commands, in run order (deduped).
  const selectedCommands = selectedActions.size
    ? slashCommands.filter((cmd) => selectedActions.has(cmd.action))
    : [];
  const plan = expandPlan(selectedCommands);

  const handleProfileChange = (value: string) => {
    if (value === NEW_PROFILE_VALUE) {
      setIsProfileDialogOpen(true);
      return;
    }
    setActiveProfileId(value);
  };

  // The profile owns the CUIT: whenever an active profile is selected, its
  // CUIT fills the input automatically (also on mount when one is persisted),
  // so the user never types it manually.
  useEffect(() => {
    if (!hasProfile) {
      return;
    }
    const profile = profiles.find((p) => p.id === activeProfileId);
    if (profile?.cuit) {
      setCuit(profile.cuit);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProfileId, profiles]);

  const launch = () => {
    if (!canRun || plan.length === 0) {
      return;
    }
    setIsLaunching(true);
    const chatId = pendingChatIdRef.current ?? generateUUID();
    const message = `${cuit} ${plan.map((cmd) => `/${cmd.action}`).join(" ")}`;
    toast({ type: "success", description: dict.launching });
    router.push(
      `/chat/${chatId}?query=${encodeURIComponent(message)}&profile=${encodeURIComponent(activeProfileId)}`
    );
  };

  return (
    <div className="flex flex-col items-center gap-6 rounded-2xl border border-border/50 bg-card/60 px-6 py-12 text-center shadow-sm">
      <GreetingHeader animated={false} />

      {/* Profile + CUIT on the same row: profile first, CUIT next to it. */}
      <div className="flex w-full max-w-2xl flex-col gap-1.5">
        <div className="flex w-full items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-border/50 bg-card/40 px-3 py-2">
            <UserIcon className="size-4 shrink-0 text-muted-foreground/60" />
            <span className="text-xs whitespace-nowrap text-muted-foreground">
              {profileDict.label}
            </span>
            <Select
              onValueChange={handleProfileChange}
              value={activeProfileId}
            >
              <SelectTrigger className="h-8 w-full rounded-lg bg-transparent px-2 text-sm shadow-none focus:ring-0">
                <SelectValue placeholder={profileDict.selectPlaceholder} />
              </SelectTrigger>
              <SelectContent className="max-w-sm rounded-xl">
                {activeProfiles.length === 0 && (
                  <div className="px-3 py-2 text-xs italic text-muted-foreground/60">
                    {profileDict.empty}
                  </div>
                )}
                {activeProfiles.map((p) => (
                  <SelectItem
                    className="text-sm"
                    key={p.id}
                    value={p.id}
                  >
                    {p.name}
                  </SelectItem>
                ))}
                <SelectItem
                  className="text-sm text-primary"
                  value={NEW_PROFILE_VALUE}
                >
                  ＋ {dict.newProfile}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Input
            className="h-10 min-w-0 flex-1 text-center font-mono"
            onChange={(e) =>
              setCuit(e.target.value.replace(/\D/g, "").slice(0, 11))
            }
            placeholder={dict.cuitPlaceholder}
            value={cuit}
          />
        </div>
        <span className="text-xs text-muted-foreground">
          {cuit.length > 0 && !cuitValid ? dict.cuitInvalid : dict.cuitHint}
        </span>
      </div>

      <div className="flex max-w-2xl flex-col gap-2">
        <div className="flex max-w-2xl flex-wrap justify-center gap-2">
          {slashCommands.map((command) => {
            const isSelected = selectedActions.has(command.action);
            return (
              <Suggestion
                className={cn(
                  "gap-1.5 disabled:cursor-not-allowed disabled:opacity-40",
                  isSelected && "border-primary/70 ring-2 ring-primary/20"
                )}
                disabled={!canRun}
                key={command.action}
                onClick={() => toggleAction(command)}
                suggestion={command.name}
                variant={isSelected ? "default" : "outline"}
              >
                {command.icon}
                {command.name}
              </Suggestion>
            );
          })}
        </div>
        <p className="text-xs text-muted-foreground/70">{dict.multiToolsHint}</p>
        {!hasProfile && (
          <p className="text-xs text-muted-foreground/70">
            {dict.selectProfileHint}
          </p>
        )}
        <div className="flex justify-center pt-2">
          <Button
            className="cursor-pointer"
            disabled={isLaunching || !canRun || selectedActions.size === 0}
            onClick={launch}
            size="sm"
            type="button"
          >
            {isLaunching && <Loader2 className="size-3.5 animate-spin" />}
            {dict.next}
          </Button>
        </div>
      </div>

      {/* Shared create dialog — a created profile is auto-selected. */}
      <ProfileFormDialog
        defaultCuit={cuit}
        onOpenChange={setIsProfileDialogOpen}
        onSaved={(created) => setActiveProfileId(created.id)}
        open={isProfileDialogOpen}
        profile={null}
      />
    </div>
  );
}