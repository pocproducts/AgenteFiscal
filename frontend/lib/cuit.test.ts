import { describe, expect, it } from "vitest";
import { applyProfileCuitToInput } from "./cuit";

describe("applyProfileCuitToInput", () => {
  it("fills the CUIT on an empty input", () => {
    expect(applyProfileCuitToInput("", "30716395541")).toBe("30716395541 ");
  });

  it("prepends the CUIT before a pending slash command", () => {
    expect(applyProfileCuitToInput("/consultaarca", "30716395541")).toBe(
      "30716395541 /consultaarca"
    );
  });

  it("prepends the CUIT before free text", () => {
    expect(applyProfileCuitToInput("consulta la deuda", "30716395541")).toBe(
      "30716395541 consulta la deuda"
    );
  });

  it("replaces a different leading CUIT and keeps the slash command", () => {
    expect(
      applyProfileCuitToInput("20324837796 /consultaarca", "30716395541")
    ).toBe("30716395541 /consultaarca");
  });

  it("replaces a 'CUIT xx' spelled-out prefix", () => {
    expect(
      applyProfileCuitToInput("CUIT 20324837796 /reporte", "30716395541")
    ).toBe("30716395541 /reporte");
  });

  it("leaves input unchanged when the same CUIT is already present", () => {
    expect(applyProfileCuitToInput("30716395541 /consultaarca", "30716395541")).toBe(
      "30716395541 /consultaarca"
    );
  });

  it("leaves input unchanged when the profile has no CUIT", () => {
    expect(applyProfileCuitToInput("/consultaarca", null)).toBe("/consultaarca");
    expect(applyProfileCuitToInput("/consultaarca", undefined)).toBe(
      "/consultaarca"
    );
  });
});