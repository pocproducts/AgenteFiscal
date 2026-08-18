# frontend/Dockerfile — Agente Fiscal frontend (Next.js, pnpm workspace)
#
# El contexto de build es la RAÍZ del repo (necesita pnpm-workspace.yaml y
# pnpm-lock.yaml del monorepo). Deployar con:
#   fly deploy . --config frontend/fly.toml
#
# Stages:
#   1. deps   — instala dependencias del workspace con pnpm (frozen lockfile)
#   2. builder— next build con output: standalone
#   3. runner — imagen mínima con el server standalone de Next.js
#
# syntax=docker/dockerfile:1

FROM node:22-alpine AS base
RUN corepack enable && corepack prepare pnpm@10.32.1 --activate
WORKDIR /repo

# ── deps: solo manifiestos, cachea la capa por pnpm-lock.yaml ────────────
# Instala el workspace COMPLETO: el frontend importa TS del paquete backend
# (frontend/lib/* → backend/* vía paths de tsconfig), así que --filter dejaría
# fuera deps que next build necesita.
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json ./frontend/
COPY backend/package.json ./backend/
RUN pnpm install --frozen-lockfile

# ── builder: código + build standalone ────────────────────────────────────
FROM base AS builder
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/frontend/node_modules ./frontend/node_modules
# El frontend importa TS del paquete backend (frontend/lib/* → backend/*):
# ese código resuelve deps (ai, zod, ...) desde backend/node_modules.
COPY --from=deps /repo/backend/node_modules ./backend/node_modules
COPY . .
# NEXT_PUBLIC_* se inyectan en el bundle en build time: pasarlas por
# [build.args] en fly.toml o `fly deploy --build-arg`.
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ARG NEXT_PUBLIC_BASE_PATH=""
ARG IS_DEMO="0"
ARG NEXT_PUBLIC_SENTRY_DSN=""
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY \
    NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH \
    IS_DEMO=$IS_DEMO \
    NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN
RUN pnpm --filter agente-fiscal-frontend build

# ── runner: solo lo que Next traza para correr ─────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /repo/frontend/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/frontend/.next/static ./frontend/.next/static
COPY --from=builder --chown=nextjs:nodejs /repo/frontend/public ./frontend/public

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "frontend/server.js"]
