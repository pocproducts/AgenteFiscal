import * as Sentry from "@sentry/nextjs";
import { SENTRY_SERVICE_TAG, sentryEnvironment } from "./lib/telemetry";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: sentryEnvironment(),
  tracesSampleRate: 1.0,
  sendDefaultPii: false,
});

Sentry.setTag("service", SENTRY_SERVICE_TAG);