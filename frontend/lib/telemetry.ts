// Telemetry conventions for the frontend side.
// The frontend and backend share ONE Sentry project (same DSN); the `service`
// tag separates their event streams. Keep this scheme in sync with
// backend/agente_fiscal/telemetry.py.

export const SENTRY_SERVICE_TAG = "frontend";

export function sentryEnvironment(): string {
  return process.env.NODE_ENV === "production" ? "production" : "development";
}