"use client";

import { useEffect, useState } from "react";

/**
 * Real-time clock: returns the current epoch ms and re-renders the consumer
 * every `intervalMs` while `enabled` is true. Used by the agent monitor and
 * the "sesiones de agentes" table so session times tick like a wall clock while
 * a session is running, instead of a frozen value.
 */
export function useLiveClock(enabled = true, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) {
      return;
    }
    // Sync immediately when (re)enabled so the clock starts at the right value.
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [enabled, intervalMs]);

  return now;
}
