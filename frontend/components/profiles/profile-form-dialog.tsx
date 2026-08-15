"use client";

import { useEffect, useState } from "react";
import { toast } from "@/components/chat/toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  isProfileApiError,
  useProfiles,
} from "@/hooks/use-profiles";
import { useLanguage } from "@/lib/i18n";
import type { Profile } from "@/lib/shared/db-types";

export function isValidCuit(cuit: string): boolean {
  if (!/^\d{11}$/.test(cuit)) {
    return false;
  }
  const digits = cuit.split("").map(Number);
  const weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
  const sum = digits
    .slice(0, 10)
    .reduce((acc, digit, index) => acc + digit * weights[index], 0);
  const remainder = sum % 11;
  const check = remainder === 0 ? 0 : 11 - remainder;
  return check !== 10 && check === digits[10];
}

type ProfileFormDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When provided the dialog edits that profile; otherwise it creates one. */
  profile?: Profile | null;
  /** Prefill CUIT on create (e.g. from the composer's CUIT field). */
  defaultCuit?: string;
  /** Invoked after a successful create/update with the persisted profile. */
  onSaved?: (profile: Profile) => void;
};

export function ProfileFormDialog({
  open,
  onOpenChange,
  profile,
  defaultCuit,
  onSaved,
}: ProfileFormDialogProps) {
  const { t } = useLanguage();
  const dict = t.panel.pages.settings.profiles;

  const { addProfile, updateProfile, isLoading } = useProfiles();

  const isEdit = !!profile;

  const [name, setName] = useState("");
  const [cuit, setCuit] = useState("");
  const [status, setStatus] = useState<"active" | "inactive">("active");
  const [submitting, setSubmitting] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);

  // Re-seed the form every time the dialog opens (shared dialog mounted once
  // and reused by the settings page + composer for different targets).
  useEffect(() => {
    if (!open) {
      return;
    }
    setName(profile?.name ?? "");
    setCuit(profile?.cuit ?? defaultCuit ?? "");
    setStatus(profile?.status ?? "active");
    setFieldError(null);
  }, [open, profile, defaultCuit]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setFieldError(dict.nameEmpty);
      return;
    }
    const normalizedCuit = cuit.trim();
    if (normalizedCuit && !isValidCuit(normalizedCuit)) {
      setFieldError(dict.invalidCuit);
      return;
    }

    setSubmitting(true);
    setFieldError(null);
    try {
      if (isEdit && profile) {
        const patch: {
          name: string;
          cuit: string | null;
          status?: "active" | "inactive";
        } = { name: name.trim(), cuit: normalizedCuit || null };
        if (status !== profile.status) {
          patch.status = status;
        }
        const updated = await updateProfile(profile.id, patch);
        onSaved?.(updated);
        toast({ type: "success", description: dict.nameUpdated });
      } else {
        const created = await addProfile(name.trim(), normalizedCuit || null);
        onSaved?.(created);
        toast({
          type: "success",
          description: dict.profileCreated.replace("{name}", created.name),
        });
      }
      onOpenChange(false);
    } catch (err) {
      if (isProfileApiError(err) && err.code === "PROFILE_CUIT_EXISTS") {
        setFieldError(dict.cuitExists);
      } else if (isProfileApiError(err) && err.code === "INVALID_CUIT") {
        setFieldError(dict.invalidCuit);
      } else {
        setFieldError(dict.unknownError);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>
              {isEdit ? dict.editDialogTitle : dict.createDialogTitle}
            </DialogTitle>
            <DialogDescription>
              {isEdit ? dict.editDialogDesc : dict.createDialogDescription}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="profile-form-name">{dict.profileNameLabel}</Label>
              <Input
                autoFocus
                className="rounded-xl"
                id="profile-form-name"
                onChange={(e) => setName(e.target.value)}
                placeholder={dict.profileNamePlaceholder}
                value={name}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="profile-form-cuit">{dict.cuitLabel}</Label>
              <Input
                className="rounded-xl font-mono"
                id="profile-form-cuit"
                onChange={(e) =>
                  setCuit(e.target.value.replace(/\D/g, "").slice(0, 11))
                }
                placeholder="20389727785"
                value={cuit}
              />
              <p className="text-xs text-muted-foreground">
                {dict.cuitOptionalHint}
              </p>
            </div>
            {isEdit && (
              <div className="space-y-1.5">
                <Label htmlFor="profile-form-status">{dict.statusLabel}</Label>
                <Select
                  onValueChange={(v) => setStatus(v as "active" | "inactive")}
                  value={status}
                >
                  <SelectTrigger
                    className="w-full rounded-xl"
                    id="profile-form-status"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl">
                    <SelectItem value="active">{dict.statusActive}</SelectItem>
                    <SelectItem value="inactive">
                      {dict.statusInactive}
                    </SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {dict.statusHint}
                </p>
              </div>
            )}
            {fieldError && (
              <p className="text-xs font-medium text-destructive">
                {fieldError}
              </p>
            )}
          </div>
          <DialogFooter className="mt-3">
            <Button
              className="rounded-xl"
              disabled={submitting}
              onClick={() => onOpenChange(false)}
              type="button"
              variant="outline"
            >
              {dict.cancel}
            </Button>
            <Button
              className="rounded-xl"
              disabled={submitting || isLoading}
              type="submit"
            >
              {submitting
                ? dict.saving
                : isEdit
                  ? dict.save
                  : dict.create}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}