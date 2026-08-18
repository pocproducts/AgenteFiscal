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

// ─────────────────────────────────────────────────────────────────────────────
// Browser tools: single source for the BFF tool-key matcher, the display
// toolName (PascalCase) and the per-tool session window.
//
// Window rule (design D3): window_ms >= task timeout + margin, so the UI never
// closes before the backend finishes:
//   - browser tools: FacilidadesTask 900s → 960s (16m); RegistroTask /
//     VencimientosDeudasTask / IIBBTask 600s → 660s (11m).
//   - deterministic engines (consultaarca / calendariovencimientosarca): no
//     browser session; short 120s window, they just need to show output.
// Windows live ONLY here (backend ToolSpec carries no window_ms).
// ─────────────────────────────────────────────────────────────────────────────

// Single canonical list of tool keys, from which both matcher regexes derive
// (avoids drift between the single-tool matcher and the multi-tool global one).
const TOOL_KEY_LIST =
  "deudavencimientos|misfacilidades|rentascordoba|sistemaregistral|consultaarca|calendariovencimientosarca";

/** Matches the six browser-tool keys anywhere in a direct command. */
export const TOOL_KEY_RE = new RegExp(`\\b(?:${TOOL_KEY_LIST})\\b`, "i");

/**
 * Matches EVERY tool key in a message, including the `informefiscal` /
 * `enviarmail` macros — used to parse multi-tool launch messages so the BFF
 * can forward the whole selection (not just the first token) to the backend.
 */
export const TOOL_KEYS_RE_GLOBAL = new RegExp(
  `\\b(?:${TOOL_KEY_LIST}|informefiscal|enviarmail)\\b`,
  "gi"
);

/**
 * Deterministic engine tools: padrón A5 / rules engine, NO live browser
 * session. The BFF routes them through the plain backend chat path, so they
 * never open the agent monitor sidebar (no `data-agent-session-start`).
 */
export const NO_MONITOR_TOOLS = [
  "consultaarca",
  "calendariovencimientosarca",
] as const;

/** PascalCase display name per tool key (`data-agent-session-start.toolName`). */
export const TOOL_NAMES: Record<string, string> = {
  sistemaregistral: "SistemaRegistral",
  deudavencimientos: "DeudaVencimientos",
  misfacilidades: "MisFacilidades",
  rentascordoba: "RentasCordoba",
  consultaarca: "ConsultaArca",
  calendariovencimientosarca: "CalendarioVencimientosArca",
};

/** Per-tool session window (ms); overrides the default for every tool key. */
export const TOOL_WINDOW_OVERRIDES: Record<string, number> = {
  sistemaregistral: 11 * 60_000, // 660s ≥ RegistroTask 600s + margin
  deudavencimientos: 11 * 60_000, // 660s ≥ VencimientosDeudasTask 600s + margin
  misfacilidades: 16 * 60_000, // 960s ≥ FacilidadesTask 900s + margin
  rentascordoba: 11 * 60_000, // 660s ≥ IIBBTask 600s + margin
  consultaarca: 2 * 60_000, // deterministic engine (no browser)
  calendariovencimientosarca: 2 * 60_000, // deterministic engine (no browser)
};

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
