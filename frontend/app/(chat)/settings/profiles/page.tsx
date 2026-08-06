"use client";

import { Check, Globe, Key, Pencil, Plus, Trash2, Users } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
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
import { type Profile, useProfiles } from "@/hooks/use-profiles";
import { useLanguage } from "@/lib/i18n";

export default function ProfilesSettingsPage() {
  const {
    profiles,
    addProfile,
    updateProfileName,
    deleteProfile,
    setProfileAuth,
  } = useProfiles();

  const { t } = useLanguage();
  const dict = t.panel.pages.settings.profiles;

  // Create Modal
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [selectedDomains, setSelectedDomains] = useState<string[]>([
    "arca.gob.ar",
  ]);

  // Edit Modal
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [editingId, setEditingId] = useState("");
  const [editingName, setEditingName] = useState("");

  // Auth Modal
  const [isAuthOpen, setIsAuthOpen] = useState(false);
  const [authProfile, setAuthProfile] = useState<Profile | null>(null);
  const [cuitInput, setCuitInput] = useState("");
  const [passwordInput, setPasswordInput] = useState("");
  const [isAuthenticating, setIsAuthenticating] = useState(false);

  const handleCreateProfile = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) {
      toast.error(dict.invalidName);
      return;
    }
    const added = addProfile(newName.trim(), selectedDomains);
    toast.success(dict.profileCreated.replace("{name}", added.name));
    setNewName("");
    setSelectedDomains(["arca.gob.ar"]);
    setIsCreateOpen(false);
  };

  const handleEditProfile = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingName.trim()) {
      toast.error(dict.nameEmpty);
      return;
    }
    updateProfileName(editingId, editingName.trim());
    toast.success(dict.nameUpdated);
    setIsEditOpen(false);
  };

  const handleSetupAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (cuitInput.length !== 11) {
      toast.error(dict.invalidCuit);
      return;
    }
    if (!passwordInput.trim()) {
      toast.error(dict.passwordEmpty);
      return;
    }
    setIsAuthenticating(true);
    if (authProfile) {
      await setProfileAuth(authProfile.id, true);
      toast.success(dict.authSet.replace("{name}", authProfile.name));
    }
    setIsAuthenticating(false);
    setIsAuthOpen(false);
    setCuitInput("");
    setPasswordInput("");
  };

  const toggleDomain = (domain: string) => {
    setSelectedDomains((prev) =>
      prev.includes(domain)
        ? prev.filter((d) => d !== domain)
        : [...prev, domain]
    );
  };

  const AVAILABLE_DOMAINS = [
    "arca.gob.ar",
    "rentascordoba.gob.ar",
    "afip.gob.ar",
    "muni-cba.gov.ar",
  ];

  return (
    <div className="flex flex-1 flex-col h-full bg-background/50 overflow-y-auto">
      {/* Header */}
      <div className="flex flex-col border-b border-border/40">
        {/* Title + subtitle */}
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

        {/* Separator */}
        <div className="border-t border-border/40" />

        {/* Total count + New Profile button */}
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
              onClick={() => setIsCreateOpen(true)}
            >
              <Plus className="h-4 w-4" />
              {dict.newProfile}
            </Button>
          </div>
        </div>
      </div>

      {/* Cards */}
      <div className="flex flex-col items-center gap-4 px-6 py-8 w-full max-w-2xl mx-auto">
        {profiles.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted/50">
              <Users className="h-7 w-7 text-muted-foreground/40" />
            </div>
            <p className="text-muted-foreground text-sm">{dict.empty}</p>
            <Button
              className="rounded-xl mt-1"
              onClick={() => setIsCreateOpen(true)}
              variant="outline"
            >
              <Plus className="h-4 w-4 mr-1.5" /> {dict.createFirst}
            </Button>
          </div>
        )}

        {profiles.map((p) => (
          <div
            className="w-full rounded-2xl border border-border/50 bg-card/60 shadow-sm backdrop-blur-sm overflow-hidden transition-all hover:shadow-md hover:border-border/80"
            key={p.id}
          >
            {/* Card header */}
            <div className="flex items-center justify-between px-5 pt-5 pb-4 border-b border-border/30">
              <div className="flex items-center gap-3">
                {/* Avatar */}
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary font-semibold text-sm shrink-0">
                  {p.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <p className="font-semibold text-foreground leading-tight">
                    {p.name}
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
                  onClick={() => {
                    setEditingId(p.id);
                    setEditingName(p.name);
                    setIsEditOpen(true);
                  }}
                  size="sm"
                  variant="ghost"
                >
                  <Pencil className="h-3.5 w-3.5" /> {dict.rename}
                </Button>

                <Button
                  className="rounded-lg text-xs flex items-center gap-1 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setAuthProfile(p);
                    setIsAuthOpen(true);
                  }}
                  size="sm"
                  variant="ghost"
                >
                  <Key className="h-3.5 w-3.5" /> {dict.setupAuth}
                </Button>

                <Button
                  className="rounded-lg text-xs flex items-center gap-1 text-destructive hover:bg-destructive/10"
                  onClick={() => {
                    deleteProfile(p.id);
                    toast.success(dict.profileDeleted);
                  }}
                  size="sm"
                  variant="ghost"
                >
                  <Trash2 className="h-3.5 w-3.5" /> {dict.delete}
                </Button>
              </div>
            </div>

            {/* Card body */}
            <div className="px-5 py-4 flex flex-col gap-3">
              {/* Domains */}
              <div className="flex items-start gap-2">
                <Globe className="h-3.5 w-3.5 text-muted-foreground/60 mt-0.5 shrink-0" />
                <div className="flex flex-wrap gap-1.5">
                  {p.cookiesDomains.length > 0 ? (
                    p.cookiesDomains.map((dom) => (
                      <Badge
                        className="font-mono text-[10px] px-2 py-0.5 border-border/60 bg-muted/30"
                        key={dom}
                        variant="outline"
                      >
                        {dom}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-xs text-muted-foreground/50 italic">
                      {dict.noDomains}
                    </span>
                  )}
                </div>
              </div>

              {/* Created date */}
              <p className="text-xs text-muted-foreground/70">
                {dict.createdOn}{" "}
                <span className="font-medium text-muted-foreground">
                  {p.createdAt}
                </span>
              </p>
            </div>
          </div>
        ))}
      </div>

      {/* CREATE DIALOG */}
      <Dialog onOpenChange={setIsCreateOpen} open={isCreateOpen}>
        <DialogContent className="max-w-md">
          <form onSubmit={handleCreateProfile}>
            <DialogHeader>
              <DialogTitle>{dict.createDialogTitle}</DialogTitle>
              <DialogDescription>
                {dict.createDialogDescription}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-muted-foreground">
                  {dict.profileNameLabel}
                </label>
                <Input
                  autoFocus
                  className="rounded-xl"
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder={dict.profileNamePlaceholder}
                  value={newName}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-muted-foreground">
                  {dict.cookieDomainsLabel}
                </label>
                <div className="grid grid-cols-2 gap-2 mt-1">
                  {AVAILABLE_DOMAINS.map((domain) => {
                    const selected = selectedDomains.includes(domain);
                    return (
                      <button
                        className={`flex items-center justify-between p-2.5 rounded-lg border text-left text-xs transition-all ${
                          selected
                            ? "border-primary/50 bg-primary/5 text-primary font-medium"
                            : "border-border/60 hover:bg-muted/50 text-muted-foreground"
                        }`}
                        key={domain}
                        onClick={() => toggleDomain(domain)}
                        type="button"
                      >
                        <span>{domain}</span>
                        {selected && (
                          <Check className="h-3.5 w-3.5 stroke-[3px]" />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <DialogFooter className="mt-3">
              <Button
                className="rounded-xl"
                onClick={() => setIsCreateOpen(false)}
                type="button"
                variant="outline"
              >
                {dict.cancel}
              </Button>
              <Button className="rounded-xl" type="submit">
                {dict.create}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* EDIT DIALOG */}
      <Dialog onOpenChange={setIsEditOpen} open={isEditOpen}>
        <DialogContent className="max-w-sm">
          <form onSubmit={handleEditProfile}>
            <DialogHeader>
              <DialogTitle>{dict.renameDialogTitle}</DialogTitle>
              <DialogDescription>{dict.renameDialogDesc}</DialogDescription>
            </DialogHeader>
            <div className="py-4">
              <Input
                className="rounded-xl"
                onChange={(e) => setEditingName(e.target.value)}
                placeholder={dict.profileNameLabel}
                value={editingName}
              />
            </div>
            <DialogFooter>
              <Button
                className="rounded-xl"
                onClick={() => setIsEditOpen(false)}
                type="button"
                variant="outline"
              >
                {dict.cancel}
              </Button>
              <Button className="rounded-xl" type="submit">
                {dict.save}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* AUTH DIALOG */}
      <Dialog onOpenChange={setIsAuthOpen} open={isAuthOpen}>
        <DialogContent className="max-w-md">
          <form onSubmit={handleSetupAuth}>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Key className="h-5 w-5 text-primary" /> {dict.authDialogTitle}
              </DialogTitle>
              <DialogDescription>{dict.authDialogDesc}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-muted-foreground">
                  {dict.cuitLabel}
                </label>
                <Input
                  className="rounded-xl font-mono"
                  disabled={isAuthenticating}
                  onChange={(e) =>
                    setCuitInput(e.target.value.replace(/\D/g, "").slice(0, 11))
                  }
                  placeholder="20389727785"
                  value={cuitInput}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-muted-foreground">
                  {dict.passwordLabel}
                </label>
                <Input
                  className="rounded-xl"
                  disabled={isAuthenticating}
                  onChange={(e) => setPasswordInput(e.target.value)}
                  placeholder="••••••••••••"
                  type="password"
                  value={passwordInput}
                />
              </div>
            </div>
            <DialogFooter className="mt-3">
              <Button
                className="rounded-xl"
                disabled={isAuthenticating}
                onClick={() => {
                  setIsAuthOpen(false);
                  setCuitInput("");
                  setPasswordInput("");
                }}
                type="button"
                variant="outline"
              >
                {dict.cancel}
              </Button>
              <Button
                className="rounded-xl"
                disabled={isAuthenticating}
                type="submit"
              >
                {isAuthenticating ? dict.simulating : dict.authenticate}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
