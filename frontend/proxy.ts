import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

// Personal-first guard: the chat (the core product) requires an authenticated
// user. A signed-in user without an active organization uses their
// auto-provisioned personal tenant (tenantKey falls back to `personal:<userId>`)
// and reaches the chat directly. Users without an account go to /login. The
// /tenant page remains reachable via navigation for org users who want to
// create or select an organization.
export default clerkMiddleware(async (auth, req) => {
  const { userId } = await auth();
  const { pathname } = req.nextUrl;

  const isChatRoute =
    pathname === "/chat" ||
    pathname.startsWith("/chat/") ||
    pathname.startsWith("/agent-sessions") ||
    pathname.startsWith("/analytics") ||
    pathname.startsWith("/settings") ||
    pathname.startsWith("/remote-browser");

  if (!isChatRoute) {
    return;
  }

  if (!userId) {
    const loginUrl = new URL("/login", req.url);
    return NextResponse.redirect(loginUrl);
  }
});

export const config = {
  matcher: [
    // Run on all routes except Next.js internals and static assets.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
