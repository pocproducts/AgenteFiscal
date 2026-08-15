import { ArrowRightIcon, UserIcon } from "lucide-react";
import { cookies } from "next/headers";
import Link from "next/link";
import { OrganizationListWidget } from "@/components/auth/clerk-widgets";
import { Button } from "@/components/ui/button";
import type { Language } from "@/lib/i18n";
import { getDictionary } from "@/lib/i18n/server";

/**
 * Tenant selection. The primary path is the personal space (the backend
 * auto-provisions the personal tenant from the Clerk user id), so it's the
 * prominent CTA; the Clerk organization list stays available underneath for
 * members of real organizations (hidePersonal keeps it from mixing concerns).
 */
export default async function TenantSelectionPage() {
  const cookieStore = await cookies();
  const raw = cookieStore.get("optimus-lang")?.value;
  const locale: Language = raw === "en" || raw === "es" ? raw : "es";
  const t = getDictionary(locale);
  const dict = t.auth;

  return (
    <div className="flex w-full items-center justify-center">
      <div className="flex w-full max-w-md flex-col gap-6">
        {/* Personal space — primary CTA */}
        <div className="rounded-2xl border border-border/50 bg-card/60 p-5 shadow-sm">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <UserIcon className="size-4" />
            </div>
            <h2 className="text-base font-semibold text-foreground">
              {dict.personalSpaceTitle}
            </h2>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {dict.personalSpaceHint}
          </p>
          <Button asChild className="mt-4 w-full rounded-xl">
            <Link href="/chat">
              {dict.personalSpaceCta}
              <ArrowRightIcon className="ml-1.5 size-4" />
            </Link>
          </Button>
        </div>

        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-border/40" />
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground/50">
            {dict.orLabel}
          </span>
          <div className="h-px flex-1 bg-border/40" />
        </div>

        <OrganizationListWidget
          afterCreateOrganizationUrl="/chat"
          afterSelectOrganizationUrl="/chat"
          hidePersonal={true}
        />
      </div>
    </div>
  );
}