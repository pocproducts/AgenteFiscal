export const user = {} as any;
export const chat = {} as any;
export const message = {} as any;
export const vote = {} as any;
export const document = {} as any;
export const suggestion = {} as any;
export const stream = {} as any;

export interface User {
  id: string;
  email: string;
  password?: string | null;
  name?: string | null;
  emailVerified: boolean;
  image?: string | null;
  isAnonymous: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface Chat {
  id: string;
  createdAt: Date;
  title: string;
  userId: string;
  tenantId: string;
  visibility: "public" | "private";
  status: "running" | "done";
  agentActivity?: unknown;
}

export interface DBMessage {
  id: string;
  chatId: string;
  role: string;
  parts: any;
  attachments: any;
  createdAt: Date;
}

export interface Vote {
  chatId: string;
  messageId: string;
  isUpvoted: boolean;
}

export interface Document {
  id: string;
  createdAt: Date;
  title: string;
  content: string | null;
  kind: "text" | "code" | "image" | "sheet";
  userId: string;
  tenantId: string;
}

export interface Suggestion {
  id: string;
  documentId: string;
  documentCreatedAt: Date;
  originalText: string;
  suggestedText: string;
  description?: string | null;
  isResolved: boolean;
  userId: string;
  createdAt: Date;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  ownerUserId: string;
  createdAt: Date;
}

export interface TenantMember {
  tenantId: string;
  userId: string;
}

