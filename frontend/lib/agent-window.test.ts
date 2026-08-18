import { describe, expect, it } from "vitest";

import {
  TODO_TOOL_KEYS,
  expandPlan,
  slashCommands,
} from "@/components/chat/slash-commands";

import {
  AGENT_SESSION_WINDOW_MS,
  NO_MONITOR_TOOLS,
  TOOL_KEY_RE,
  TOOL_KEYS_RE_GLOBAL,
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

describe("TOOL_KEYS_RE_GLOBAL (multi-tool matcher)", () => {
  it("finds every tool key in a multi-tool message (not just the first)", () => {
    const msg =
      "20301234561 /consultaarca /sistemaregistral /misfacilidades /deudavencimientos /rentascordoba /calendariovencimientosarca /informefiscal /enviarmail";
    const matches = msg.match(TOOL_KEYS_RE_GLOBAL) ?? [];
    expect(matches.map((m) => m.toLowerCase())).toEqual([
      "consultaarca",
      "sistemaregistral",
      "misfacilidades",
      "deudavencimientos",
      "rentascordoba",
      "calendariovencimientosarca",
      "informefiscal",
      "enviarmail",
    ]);
  });

  it("matches the informefiscal / enviarmail macros too", () => {
    expect("CUIT 20-12345678-9 /informefiscal /enviarmail".match(TOOL_KEYS_RE_GLOBAL)).toContain(
      "informefiscal"
    );
    expect("CUIT 20-12345678-9 /informefiscal /enviarmail".match(TOOL_KEYS_RE_GLOBAL)).toContain(
      "enviarmail"
    );
  });

  it("matches a single tool exactly like TOOL_KEY_RE", () => {
    for (const key of ALL_TOOL_KEYS) {
      expect(`${key} CUIT 20-12345678-9`.match(TOOL_KEYS_RE_GLOBAL)).toContain(
        key
      );
    }
  });

  it("is case-insensitive", () => {
    expect("MisFacilidades DeudaVencimientos".match(TOOL_KEYS_RE_GLOBAL)).toEqual([
      "MisFacilidades",
      "DeudaVencimientos",
    ]);
  });
});

describe("expandPlan (multi-command plan expansion)", () => {
  const planOf = (actions: string[]) => {
    const cmds = actions
      .map((a) => slashCommands.find((c) => c.action === a))
      .filter((c): c is (typeof slashCommands)[number] => c !== undefined);
    return expandPlan(cmds).map((c) => c.action);
  };

  it("keeps a single data command as-is", () => {
    expect(planOf(["misfacilidades"])).toEqual(["misfacilidades"]);
  });

  it("expands todo to the full canonical backend order", () => {
    const plan = planOf(["todo"]);
    expect(plan).toEqual(TODO_TOOL_KEYS);
  });

  it("dedupes tools merged with todo keeping the canonical order", () => {
    const plan = planOf(["todo", "misfacilidades", "enviarmail"]);
    expect(plan.filter((a) => a === "misfacilidades")).toHaveLength(1);
    expect(plan.filter((a) => a === "enviarmail")).toHaveLength(1);
    expect(plan).toEqual(TODO_TOOL_KEYS);
  });

  it("appends informefiscal/enviarmail after the data tools when selected individually", () => {
    expect(planOf(["deudavencimientos", "enviarmail", "consultaarca", "informefiscal"])).toEqual([
      "deudavencimientos",
      "consultaarca",
      "informefiscal",
      "enviarmail",
    ]);
  });

  it("returns the canonical backend order regardless of selection order", () => {
    expect(planOf(["rentascordoba", "sistemaregistral", "rentascordoba"])).toEqual([
      "sistemaregistral",
      "rentascordoba",
    ]);
  });

  it("is stable for the empty selection", () => {
    expect(expandPlan([])).toEqual([]);
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
