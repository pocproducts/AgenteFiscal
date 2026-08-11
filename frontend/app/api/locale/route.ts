import { type NextRequest, NextResponse } from "next/server";

const OPTIMUS_LANG = "optimus-lang";
const MAX_AGE = 60 * 60 * 24 * 365; // 1 year

export function isSupportedLang(value: unknown): value is "en" | "es" {
  return value === "en" || value === "es";
}

/**
 * Sets the `optimus-lang` cookie so the server can render the correct locale
 * on the next navigation. Called by the client toggle after updating
 * localStorage. Respects NEXT_PUBLIC_BASE_PATH naturally because Next.js
 * scopes cookies to the active base path.
 */
export async function PUT(req: NextRequest) {
  let lang: unknown = null;
  try {
    const body = await req.json();
    lang = body?.lang;
  } catch {
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }

  if (!isSupportedLang(lang)) {
    return NextResponse.json({ error: "invalid_lang" }, { status: 400 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set(OPTIMUS_LANG, lang, {
    path: "/",
    maxAge: MAX_AGE,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });
  return res;
}
