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
