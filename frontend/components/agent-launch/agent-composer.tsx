"use client";

import { Loader2, UserIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { Suggestion } from "@/components/ai-elements/suggestion";
import { GreetingHeader } from "@/components/chat/greeting-header";
import {
  expandCommandPlan,
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
import { generateUUID } from "@/lib/utils";

/** Sentinel select value that opens the shared "new profile" dialog. */
const NEW_PROFILE_VALUE = "__new_profile__";

/**
 * The "start a new report" layout — the only place that launches a fiscal
 * automation (a bare empty chat redirects here, see EmptyChatRedirect in
 * components/chat/messages.tsx). Picking a fiscal tool launches a new chat
 * that auto-sends "<cuit> /<tool>" via the `?query=` param `use-active-chat`
 * consumes on mount.
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
  const [pendingAction, setPendingAction] = useState<SlashCommand | null>(null);
  const [isLaunching, setIsLaunching] = useState(false);
  const [isProfileDialogOpen, setIsProfileDialogOpen] = useState(false);
  const cuitValid = cuit.length === 11;
  const canRun = cuitValid && hasProfile;

  // Generated (and the /chat/[id] route prefetched) as soon as the user picks
  // a tool — not inside launch() — so the route's JS/RSC payload is already
  // warm by the time they confirm on the plan screen, instead of eating a
  // multi-second on-demand compile right after clicking "Run".
  const pendingChatIdRef = useRef<string | null>(null);

  const selectAction = useCallback(
    (command: SlashCommand) => {
      const chatId = generateUUID();
      pendingChatIdRef.current = chatId;
      router.prefetch(`/chat/${chatId}`);
      setPendingAction(command);
    },
    [router]
  );

  const handleProfileChange = (value: string) => {
    if (value === NEW_PROFILE_VALUE) {
      setIsProfileDialogOpen(true);
      return;
    }
    setActiveProfileId(value);
    // Selecting a profile with a stored CUIT completes the CUIT field, so the
    // user never has to retype it.
    const profile = profiles.find((p) => p.id === value);
    if (profile?.cuit) {
      setCuit(profile.cuit);
    }
  };

  const launch = (action: string) => {
    if (!canRun) {
      return;
    }
    setIsLaunching(true);
    const chatId = pendingChatIdRef.current ?? generateUUID();
    const message = `${cuit} /${action}`;
    toast({ type: "success", description: dict.launching });
    router.push(
      `/chat/${chatId}?query=${encodeURIComponent(message)}&profile=${encodeURIComponent(activeProfileId)}`
    );
  };

  const plan = pendingAction ? expandCommandPlan(pendingAction) : [];

  return (
    <div className="flex flex-col items-center gap-6 rounded-2xl border border-border/50 bg-card/60 px-6 py-12 text-center shadow-sm">
      <GreetingHeader animated={false} />

      <div className="flex w-full max-w-sm flex-col gap-1.5">
        <Input
          className="text-center font-mono"
          onChange={(e) =>
            setCuit(e.target.value.replace(/\D/g, "").slice(0, 11))
          }
          placeholder={dict.cuitPlaceholder}
          value={cuit}
        />
        <span className="text-xs text-muted-foreground">
          {cuit.length > 0 && !cuitValid ? dict.cuitInvalid : dict.cuitHint}
        </span>
      </div>

      {/* Profile selector */}
      <div className="flex w-full max-w-sm items-center gap-2 rounded-xl border border-border/50 bg-card/40 px-3 py-2">
        <UserIcon className="size-4 shrink-0 text-muted-foreground/60" />
        <span className="text-xs whitespace-nowrap text-muted-foreground">
          {profileDict.label}
        </span>
        <Select
          onValueChange={handleProfileChange}
          value={activeProfileId}
        >
          <SelectTrigger className="h-8 flex-1 rounded-lg bg-transparent px-2 text-sm shadow-none focus:ring-0">
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
                {p.cuit ? (
                  <>
                    {" "}
                    <span className="font-mono text-xs text-muted-foreground/60">
                      · {p.cuit}
                    </span>
                  </>
                ) : null}
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

      {pendingAction ? (
        <div className="flex w-full max-w-2xl flex-col gap-4 rounded-2xl border border-border/50 bg-card/40 px-6 py-5 text-left">
          <div>
            <h3 className="font-semibold text-base text-foreground">
              {dict.planTitle}
            </h3>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {dict.planHint}
            </p>
          </div>
          <ol className="flex flex-col gap-2">
            {plan.map((step, index) => (
              <li
                className="flex items-center gap-3 rounded-xl border border-border/40 bg-card/60 px-3 py-2"
                key={step.action}
              >
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted-foreground/10 text-[10px] font-semibold text-muted-foreground">
                  {index + 1}
                </span>
                <span className="flex items-center gap-2 text-sm text-foreground">
                  {step.icon}
                  {step.name}
                </span>
              </li>
            ))}
          </ol>
          <div className="flex flex-col items-end gap-1.5">
            {!hasProfile && (
              <p className="text-xs text-muted-foreground/70">
                {dict.selectProfileHint}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button
                className="cursor-pointer"
                disabled={isLaunching}
                onClick={() => setPendingAction(null)}
                size="sm"
                type="button"
                variant="ghost"
              >
                {dict.cancel}
              </Button>
              <Button
                className="cursor-pointer"
                disabled={isLaunching || !canRun}
                onClick={() => launch(pendingAction.action)}
                size="sm"
                type="button"
              >
                {isLaunching && <Loader2 className="size-3.5 animate-spin" />}
                {dict.run}
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex max-w-2xl flex-col gap-2">
          <div className="flex max-w-2xl flex-wrap justify-center gap-2">
            {slashCommands.map((command) => (
              <Suggestion
                className="gap-1.5 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!canRun}
                key={command.action}
                onClick={() => selectAction(command)}
                suggestion={command.name}
              >
                {command.icon}
                {command.name}
              </Suggestion>
            ))}
          </div>
          {!hasProfile && (
            <p className="text-xs text-muted-foreground/70">
              {dict.selectProfileHint}
            </p>
          )}
        </div>
      )}

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