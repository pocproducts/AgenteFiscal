import { initBotId } from "botid/client/core";
import * as Sentry from "@sentry/nextjs";

initBotId({
  protect: [
    {
      path: "/api/chat",
      method: "POST",
    },
  ],
});

// Sentry: instrument router navigations for tracing (client-side hook).
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
