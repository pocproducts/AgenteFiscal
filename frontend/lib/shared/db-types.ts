export type {
  Chat,
  DBMessage,
  Document,
  Suggestion,
  User,
  Vote,
} from "@/lib/db/schema";

/**
 * Minimal user shape consumed by the authenticated panel components.
 * Populated from Clerk (server layout).
 */
export interface PanelUser {
  id: string;
  email?: string | null;
}

/**
 * Minimal authenticated session shape for AI tools.
 * Replaces the removed NextAuth Session type.
 */
export interface PanelSession {
  user?: Pick<PanelUser, "id"> | null;
}

/**
 * Tenant execution profile (backend /v1/profiles). Consumed by the panel
 * components and the chat BFF; `cuit` and `status` gate report generation
 * (the backend enforces: reports require an ACTIVE profile).
 */
export type ProfileStatus = "active" | "inactive";

export interface Profile {
  id: string;
  name: string;
  cuit: string | null;
  status: ProfileStatus;
  config: Record<string, unknown>;
  createdAt: string;
}
