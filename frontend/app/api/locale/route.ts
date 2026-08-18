import { type NextRequest, NextResponse } from "next/server";

const OPTIMUS_LANG = "optimus-lang";
const MAX_AGE = 60 * 60 * 24 * 365; // 1 year

export function isSupportedLang(value: unknown): value is "en" | "es" {
  return value === "en" || value === "es";
}

/**
 * Spanish is the only supported language. The route still accepts a request
 * body for backwards compatibility, but any value other than "es" is coerced
 * to "es" so the persisted cookie can never be English.
 */
export async function PUT(req: NextRequest) {
  try {
    await req.json();
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }

  const res = NextResponse.json({ ok: true, lang: "es" });
  res.cookies.set(OPTIMUS_LANG, "es", {
    path: "/",
    maxAge: MAX_AGE,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });
  return res;
}
