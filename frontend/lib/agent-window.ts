// ─────────────────────────────────────────────────────────────────────────────
// Single source of truth for the live-agent session window.
//
// The UI contract works like this:
//   - The BFF route (`app/(chat)/api/chat/route.ts`) advertises `windowMs` in
//     the `data-agent-session-start` stream event so the client knows for how
//     long the live browser + agent monitor stay open after the command fires.
//   - Every consumer (sidebar clock, "sesiones de agentes" table) reads the
//     same `windowMs` value shipped in the event, so they always agree with the
//     backend window without duplicating the number anywhere.
//
// To change the window length tomorrow, edit ONLY this constant: the BFF route
// and the streamed contract both derive from it, so nothing else needs to move.
// ─────────────────────────────────────────────────────────────────────────────

export const AGENT_SESSION_WINDOW_MS = 10 * 60_000;

/** Formats a duration as a wall clock (`mm:ss`; `h:mm:ss` when ≥ 1h). */
export function formatClock(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) {
    return "00:00";
  }
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${mm}:${ss}`
    : `${mm}:${ss}`;
}
