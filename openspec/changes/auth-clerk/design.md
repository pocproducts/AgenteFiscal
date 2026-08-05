# Design: Auth Clerk & Folder Restructure (Clean & Hexagonal)

## Directory Structure

We will restructure the application into two main folders: `/backend` and `/frontend`.

```
├── backend/
│   ├── auth/
│   │   ├── domain/
│   │   │   ├── entities/
│   │   │   │   ├── user.entity.ts
│   │   │   │   └── tenant.entity.ts
│   │   │   └── ports/
│   │   │       └── auth.port.ts
│   │   └── infrastructure/
│   │       ├── adapters/
│   │       │   ├── clerk-auth.adapter.ts
│   │       │   ├── in-memory-auth.adapter.ts
│   │       │   └── auth.factory.ts
│   │       └── middleware/
│   │           └── clerk-middleware.ts (referenced by /proxy.ts)
│   ├── db/
│   │   ├── schema.ts (moved from lib/db/schema.ts)
│   │   └── queries.ts (moved from lib/db/queries.ts)
│   ├── ai/ (moved from lib/ai/)
│   └── artifacts/ (moved from lib/artifacts/)
├── frontend/
│   ├── auth/
│   │   └── presentation/
│   │       ├── context/
│   │       │   └── auth.context.tsx
│   │       └── hooks/
│   │           └── use-auth.ts
│   ├── components/ (moved from /components)
│   ├── hooks/ (moved from /hooks)
│   ├── i18n/ (moved from lib/i18n)
│   └── editor/ (moved from lib/editor)
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx (SignIn UI)
│   │   └── register/page.tsx (SignUp UI)
│   ├── (chat)/
│   └── layout.tsx (wraps ClerkProvider)
└── tsconfig.json (defines import redirects)
```

---

## Technical Approach

### 1. tsconfig.json Paths Redirection
To prevent breaking existing files, we will map legacy import paths via tsconfig:
```json
    "paths": {
      "@/*": ["./*"],
      "@/backend/*": ["./backend/*"],
      "@/frontend/*": ["./frontend/*"],
      "@/components/*": ["./frontend/components/*"],
      "@/hooks/*": ["./frontend/hooks/*"],
      "@/lib/db/*": ["./backend/db/*"],
      "@/lib/ai/*": ["./backend/ai/*"],
      "@/lib/artifacts/*": ["./backend/artifacts/*"],
      "@/lib/i18n": ["./frontend/i18n/index.ts", "./frontend/i18n"],
      "@/lib/i18n/*": ["./frontend/i18n/*"],
      "@/lib/editor/*": ["./frontend/editor/*"]
    }
```

### 2. Hexagonal Auth Port & Entities
In `backend/auth/domain/ports/auth.port.ts`:
```typescript
export interface AuthUser {
  id: string;
  email: string;
  name?: string | null;
  createdAt: Date;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  ownerUserId: string;
  createdAt: Date;
}

export interface AuthPort {
  getUserByEmail(email: string): Promise<AuthUser | null>;
  getTenantById(tenantId: string): Promise<Tenant | null>;
  listTenantsForUser(userId: string): Promise<Tenant[]>;
  createTenant(userId: string, name: string): Promise<Tenant>;
}
```

### 3. Swappable Infrastructure Adapters

#### InMemoryAuthAdapter (`backend/auth/infrastructure/adapters/in-memory-auth.adapter.ts`)
Queries the file-persisted mock database.

#### ClerkAuthAdapter (`backend/auth/infrastructure/adapters/clerk-auth.adapter.ts`)
Uses `@clerk/nextjs/server`'s `clerkClient` and `auth()` helper to read organizations and members. Maps:
* Clerk `User` -> `AuthUser`
* Clerk `Organization` -> `Tenant`

#### Auth Factory (`backend/auth/infrastructure/adapters/auth.factory.ts`)
```typescript
import { InMemoryAuthAdapter } from './in-memory-auth.adapter';
import { ClerkAuthAdapter } from './clerk-auth.adapter';
import { AuthPort } from '../../domain/ports/auth.port';

let cachedAdapter: AuthPort | null = null;

export function getAuthAdapter(): AuthPort {
  if (cachedAdapter) return cachedAdapter;
  
  if (process.env.AUTH_ADAPTER === 'clerk') {
    cachedAdapter = new ClerkAuthAdapter();
  } else {
    cachedAdapter = new InMemoryAuthAdapter();
  }
  return cachedAdapter;
}
```

### 4. Clean Frontend Presentation Layer (`frontend/auth/presentation`)

We expose `AuthProvider` and `useAuth()` to isolate components from the Clerk SDK:
```typescript
// frontend/auth/presentation/context/auth.context.tsx
import React, { createContext, useContext } from 'react';

export interface AuthContextType {
  user: any | null;
  tenant: any | null;
  tenants: any[];
  status: 'loading' | 'authenticated' | 'unauthenticated';
  signIn: (email?: string, password?: string) => Promise<void>;
  signOut: () => Promise<void>;
  createTenant: (name: string) => Promise<void>;
  switchTenant: (tenantId: string) => Promise<void>;
}
```
* **In-memory mode**: Resolves locally or via NextAuth (if active) / state.
* **Clerk mode**: Resolves via Clerk client-side hooks (`useAuth()`, `useUser()`, `useOrganization()`, `useOrganizationList()`).

### 5. Middleware and Proxy Config (`proxy.ts`)
Since this is Next.js 16, the root middleware boundary file is `/proxy.ts` (instead of `middleware.ts`).
```typescript
// proxy.ts
import { clerkMiddleware } from "@clerk/nextjs/server";

export default clerkMiddleware(async (auth, request) => {
  // Protect /chat routes
  if (request.nextUrl.pathname.startsWith('/chat')) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
};
```

---

## Migration Steps

1. **Restructure Directory Structure**:
   * Create `backend/` and `frontend/` folders.
   * Move `lib/db/` -> `backend/db/`.
   * Move `lib/ai/` -> `backend/ai/`.
   * Move `lib/artifacts/` -> `backend/artifacts/`.
   * Move `components/` -> `frontend/components/`.
   * Move `hooks/` -> `frontend/hooks/`.
   * Move `lib/i18n/` -> `frontend/i18n/`.
   * Move `lib/editor/` -> `frontend/editor/`.
   * Update `tsconfig.json` path mappings.

2. **Backend Auth Hexagon**:
   * Create `backend/auth/domain/ports/auth.port.ts`.
   * Create `backend/auth/infrastructure/adapters/in-memory-auth.adapter.ts`.
   * Create `backend/auth/infrastructure/adapters/clerk-auth.adapter.ts`.
   * Create `backend/auth/infrastructure/adapters/auth.factory.ts`.

3. **Frontend Auth Seam**:
   * Create `frontend/auth/presentation/context/auth.context.tsx`.
   * Create `frontend/auth/presentation/hooks/use-auth.ts`.

4. **Clerk Integration / NextAuth Removal**:
   * Install Clerk dependencies: `@clerk/nextjs` and `@clerk/localizations`.
   * Uninstall `next-auth` and `bcrypt-ts` (if fully unused).
   * Update `app/layout.tsx` to wrap with `ClerkProvider` (conditional or Clerk only).
   * Update `app/(auth)/login/page.tsx` and `app/(auth)/register/page.tsx` to render Clerk prebuilt forms.
   * Add `proxy.ts` at the project root for middleware checks.
   * Refactor Sidebar user navigation and Chat header to consume `useAuth()`.
