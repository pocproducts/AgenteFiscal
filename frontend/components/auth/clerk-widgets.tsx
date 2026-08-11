"use client";

import dynamic from "next/dynamic";

/**
 * Clerk's prebuilt widgets mount imperatively (their own mount/unmount calls,
 * not plain JSX reconciliation), so SSR-ing them can never match what the
 * client actually renders — a Suspense boundary alone doesn't prevent that
 * mismatch. Loading them with ssr:false skips server rendering for these
 * entirely, so there's nothing for React to reconcile against on hydration.
 */
export const SignInWidget = dynamic(
  () => import("@clerk/nextjs").then((mod) => mod.SignIn),
  { ssr: false }
);

export const SignUpWidget = dynamic(
  () => import("@clerk/nextjs").then((mod) => mod.SignUp),
  { ssr: false }
);

export const OrganizationListWidget = dynamic(
  () => import("@clerk/nextjs").then((mod) => mod.OrganizationList),
  { ssr: false }
);

export const OrganizationSwitcherWidget = dynamic(
  () => import("@clerk/nextjs").then((mod) => mod.OrganizationSwitcher),
  { ssr: false }
);
