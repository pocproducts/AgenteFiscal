import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

// Multi-tenant guard: the chat (the core product) requires an authenticated
// user with an active organization. Users without an organization are sent
// to /tenant to create or select one before reaching the chat.
export default clerkMiddleware(async (auth, req) => {
  const { userId, orgId } = await auth();
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

  if (!orgId) {
    const tenantUrl = new URL("/tenant", req.url);
    return NextResponse.redirect(tenantUrl);
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
