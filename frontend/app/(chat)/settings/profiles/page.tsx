"use client";

import { IdCard, Pencil, Plus, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "@/components/chat/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ProfileFormDialog } from "@/components/profiles/profile-form-dialog";
import { isProfileApiError, useProfiles } from "@/hooks/use-profiles";
import { useLanguage } from "@/lib/i18n";
import type { Profile } from "@/lib/shared/db-types";

export default function ProfilesSettingsPage() {
  const {
    profiles,
    isLoading,
    addProfile,
    updateProfile,
    deleteProfile,
    setProfileStatus,
  } = useProfiles();

  const { t } = useLanguage();
  const dict = t.panel.pages.settings.profiles;

  // Shared create/edit dialog state.
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<Profile | null>(null);

  const openCreate = () => {
    setEditingProfile(null);
    setDialogOpen(true);
  };

  const openEdit = (p: Profile) => {
    setEditingProfile(p);
    setDialogOpen(true);
  };

  const handleDelete = async (p: Profile) => {
    try {
      await deleteProfile(p.id);
      toast({ description: dict.profileDeleted, type: "success" });
    } catch (err) {
      if (isProfileApiError(err) && err.code === "PROFILE_HAS_RUNS") {
        toast({ description: dict.deleteBlocked, type: "error" });
      } else {
        toast({ description: dict.unknownError, type: "error" });
      }
    }
  };

  const handleStatusChange = async (
    p: Profile,
    status: "active" | "inactive"
  ) => {
    if (status === p.status) {
      return;
    }
    try {
      await setProfileStatus(p.id, status);
      toast({ description: dict.statusUpdated, type: "success" });
    } catch {
      toast({ description: dict.unknownError, type: "error" });
    }
  };

  return (
    <div className="flex flex-1 flex-col h-full bg-background/50 overflow-y-auto">
      {/* Header */}
      <div className="flex flex-col border-b border-border/40">
        <div className="w-full max-w-2xl mx-auto px-6">
          <div className="flex flex-col py-8">
            <h1 className="text-lg font-semibold tracking-tight text-foreground">
              {dict.title}
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {dict.description}
            </p>
          </div>
        </div>

        <div className="border-t border-border/40" />

        <div className="w-full max-w-2xl mx-auto px-6">
          <div className="flex items-center justify-between py-3">
            <span className="text-sm text-muted-foreground">
              {dict.totalLabel}{" "}
              <span className="font-semibold text-foreground">
                {profiles.length}
              </span>
            </span>
            <Button
              className="flex items-center gap-1.5 rounded-xl"
              onClick={openCreate}
            >
              <Plus className="h-4 w-4" />
              {dict.newProfile}
            </Button>
          </div>
        </div>
      </div>

      {/* Cards */}
      <div className="flex flex-col items-center gap-4 px-6 py-8 w-full max-w-2xl mx-auto">
        {isLoading && profiles.length === 0 && (
          <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
            <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            {dict.loading}
          </div>
        )}

        {!isLoading && profiles.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted/50">
              <Users className="h-7 w-7 text-muted-foreground/40" />
            </div>
            <p className="text-muted-foreground text-sm">{dict.empty}</p>
            <Button
              className="rounded-xl mt-1"
              onClick={openCreate}
              variant="outline"
            >
              <Plus className="h-4 w-4 mr-1.5" /> {dict.createFirst}
            </Button>
          </div>
        )}

        {profiles.map((p) => (
          <ProfileCard
            key={p.id}
            dict={dict}
            profile={p}
            onEdit={() => openEdit(p)}
            onDelete={() => handleDelete(p)}
            onStatusChange={(status) => handleStatusChange(p, status)}
          />
        ))}
      </div>

      {/* Shared create/edit dialog */}
      <ProfileFormDialog
        onOpenChange={setDialogOpen}
        onSaved={(saved) => {
          // Editing could have switched its status via the backend; refreshing
          // the active seed is enough. Re-edit session targets the saved row.
          setEditingProfile(saved);
        }}
        open={dialogOpen}
        profile={editingProfile}
      />
    </div>
  );
}

function ProfileCard({
  dict,
  profile: p,
  onEdit,
  onDelete,
  onStatusChange,
}: {
  dict: ReturnType<typeof useLanguage>["t"]["panel"]["pages"]["settings"]["profiles"];
  profile: Profile;
  onEdit: () => void;
  onDelete: () => void;
  onStatusChange: (status: "active" | "inactive") => void;
}) {
  const statusStyle =
    p.status === "active"
      ? "text-emerald-500 bg-emerald-500/10"
      : "text-muted-foreground bg-muted/40";

  return (
    <div className="w-full rounded-2xl border border-border/50 bg-card/60 shadow-sm backdrop-blur-sm overflow-hidden transition-all hover:shadow-md hover:border-border/80">
      {/* Card header */}
      <div className="flex items-center justify-between px-5 pt-5 pb-4 border-b border-border/30">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary font-semibold text-sm shrink-0">
            {p.name.charAt(0).toUpperCase()}
          </div>
          <div>
            <p className="font-semibold text-foreground leading-tight flex items-center gap-2">
              {p.name}
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${statusStyle}`}
              >
                {p.status === "active" ? dict.statusActive : dict.statusInactive}
              </span>
            </p>
            <p className="text-[11px] text-muted-foreground font-mono mt-0.5">
              {p.id}
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1">
          <Button
            className="rounded-lg text-xs flex items-center gap-1 text-muted-foreground hover:text-foreground"
            onClick={onEdit}
            size="sm"
            variant="ghost"
          >
            <Pencil className="h-3.5 w-3.5" /> {dict.rename}
          </Button>
          <Select onValueChange={(v) => onStatusChange(v as "active" | "inactive")} value={p.status}>
            <SelectTrigger
              className="h-8 rounded-lg px-2 text-xs text-muted-foreground"
              size="sm"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              <SelectItem value="active">{dict.statusActive}</SelectItem>
              <SelectItem value="inactive">{dict.statusInactive}</SelectItem>
            </SelectContent>
          </Select>
          <Button
            className="rounded-lg text-xs flex items-center gap-1 text-destructive hover:bg-destructive/10"
            onClick={onDelete}
            size="sm"
            variant="ghost"
          >
            <Trash2 className="h-3.5 w-3.5" /> {dict.delete}
          </Button>
        </div>
      </div>

      {/* Card body */}
      <div className="px-5 py-4 flex flex-col gap-3">
        <div className="flex items-start gap-2">
          <IdCard className="h-3.5 w-3.5 text-muted-foreground/60 mt-0.5 shrink-0" />
          {p.cuit ? (
            <span className="font-mono text-xs text-foreground">{p.cuit}</span>
          ) : (
            <span className="text-xs text-muted-foreground/50 italic">
              {dict.cuitNone}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground/70">
          {dict.profileCreatedAt}{" "}
          <span className="font-medium text-muted-foreground">
            {p.createdAt}
          </span>
        </p>
      </div>
    </div>
  );
}