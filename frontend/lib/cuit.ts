"use client";

/**
 * UI convention for the agent input: "<CUIT> /<tool>" (e.g. "30716395541
 * /consultaarca"). CUITs stored in the active profile auto-complete the CUIT
 * part of the input when the user picks that profile, so they never have to
 * retype it.
 *
 * Returns the new input value:
 * - No profile CUIT → input unchanged.
 * - A different CUIT already leads the input → replaced with the profile CUIT
 *   (a pending slash command is preserved).
 * - No leading CUIT (empty, bare "/command", text, …) → CUIT is prefixed (with
 *   a trailing space so typing "/" reopens the slash menu).
 * - Same CUIT already present → unchanged.
 */
const CUIT_TOKEN_RE = /^(?:cuit\s+)?(\d{11})(?:\s+|$)/i;

export function applyProfileCuitToInput(
  input: string,
  cuit: string | null | undefined
): string {
  if (!cuit) {
    return input;
  }
  const match = input.match(CUIT_TOKEN_RE);
  if (match && match[1] === cuit) {
    return input;
  }
  const rest = match ? input.slice(match[0].length) : input;
  // CUIT always ends with one space so typing "/" reopens the slash menu.
  return rest ? `${cuit} ${rest}` : `${cuit} `;
}