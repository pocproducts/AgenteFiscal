import { describe, expect, it } from "vitest";

import {
  AGENT_SESSION_WINDOW_MS,
  NO_MONITOR_TOOLS,
  TOOL_KEY_RE,
  TOOL_NAMES,
  TOOL_WINDOW_OVERRIDES,
} from "./agent-window";

const ALL_TOOL_KEYS = [
  "sistemaregistral",
  "deudavencimientos",
  "misfacilidades",
  "rentascordoba",
  "consultaarca",
  "calendariovencimientosarca",
];

describe("TOOL_KEY_RE (BFF tool-key matcher)", () => {
  it("matches every tool key in a direct command", () => {
    for (const key of ALL_TOOL_KEYS) {
      expect(TOOL_KEY_RE.test(`${key} CUIT 20-12345678-9`)).toBe(true);
      expect(TOOL_KEY_RE.test(`CUIT 20-12345678-9 ${key}`)).toBe(true);
    }
  });

  it("is case-insensitive", () => {
    expect(TOOL_KEY_RE.test("MisFacilidades CUIT 20-12345678-9")).toBe(true);
    expect(TOOL_KEY_RE.test("DEUDAVENCIMIENTOS CUIT 20-12345678-9")).toBe(true);
  });

  it("rejects enviarmail and informefiscal (scope exclusions)", () => {
    expect(TOOL_KEY_RE.test("enviarmail a 20-12345678-9")).toBe(false);
    expect(TOOL_KEY_RE.test("informefiscal CUIT 20-12345678-9")).toBe(false);
  });

  it("does not fire on prose that merely contains a key as substring", () => {
    // Word boundaries required: "misfacilidades" must be a standalone token.
    expect(TOOL_KEY_RE.test("hablando de misfacilidadesx")).toBe(false);
  });
});

describe("TOOL_NAMES", () => {
  it("exposes a PascalCase display name for every tool key", () => {
    for (const key of ALL_TOOL_KEYS) {
      expect(TOOL_NAMES[key]).toBeTruthy();
    }
    expect(TOOL_NAMES.misfacilidades).toBe("MisFacilidades");
    expect(TOOL_NAMES.sistemaregistral).toBe("SistemaRegistral");
    expect(TOOL_NAMES.calendariovencimientosarca).toBe(
      "CalendarioVencimientosArca"
    );
  });
});

describe("NO_MONITOR_TOOLS (deterministic engines skip the agent monitor)", () => {
  it("covers the deterministic engine tools", () => {
    expect(NO_MONITOR_TOOLS).toContain("consultaarca");
    expect(NO_MONITOR_TOOLS).toContain("calendariovencimientosarca");
  });

  it("excludes the four browser tools (they keep the monitor)", () => {
    for (const key of [
      "sistemaregistral",
      "deudavencimientos",
      "misfacilidades",
      "rentascordoba",
    ]) {
      expect(NO_MONITOR_TOOLS).not.toContain(key);
    }
  });
});

describe("TOOL_WINDOW_OVERRIDES (window = timeout + margin)", () => {
  it("covers every tool key", () => {
    for (const key of ALL_TOOL_KEYS) {
      expect(typeof TOOL_WINDOW_OVERRIDES[key]).toBe("number");
    }
  });

  it("facilidades window covers its 900s FacilidadesTask timeout + margin", () => {
    // Window rule (design D3): window_ms >= task timeout + margin.
    expect(TOOL_WINDOW_OVERRIDES.misfacilidades).toBeGreaterThanOrEqual(
      900_000 + 60_000
    );
    expect(TOOL_WINDOW_OVERRIDES.misfacilidades).toBe(960_000);
  });

  it("browser-tool windows cover their 600s task timeouts + margin", () => {
    for (const key of [
      "sistemaregistral",
      "deudavencimientos",
      "rentascordoba",
    ]) {
      expect(TOOL_WINDOW_OVERRIDES[key]).toBeGreaterThanOrEqual(
        600_000 + 60_000
      );
      expect(TOOL_WINDOW_OVERRIDES[key]).toBe(660_000);
    }
  });

  it("deterministic engines get a short no-browser window", () => {
    for (const key of ["consultaarca", "calendariovencimientosarca"]) {
      expect(TOOL_WINDOW_OVERRIDES[key]).toBe(120_000);
    }
  });

  it("keeps the default window as the fallback for unknown tools", () => {
    // The BFF resolves `TOOL_WINDOW_OVERRIDES[tool] ?? AGENT_SESSION_WINDOW_MS`.
    expect(AGENT_SESSION_WINDOW_MS).toBe(10 * 60_000);
  });
});
