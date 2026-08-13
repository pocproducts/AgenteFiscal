import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { createClerkClient } from "@clerk/backend";
import { clerk, clerkSetup } from "@clerk/testing/playwright";
import { test as setup } from "@playwright/test";

const E2E_CLERK_USER_EMAIL = process.env.E2E_CLERK_USER_EMAIL;
const E2E_CLERK_USER_PASSWORD = process.env.E2E_CLERK_USER_PASSWORD;

const CLERK_TEST_CONFIGURED = Boolean(
  process.env.CLERK_SECRET_KEY &&
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
    E2E_CLERK_USER_EMAIL &&
    E2E_CLERK_USER_PASSWORD
);

const ORG_NAME = "E2E Test Org";
const storageStateFile = path.join(
  process.cwd(),
  "playwright",
  ".clerk",
  "user.json"
);

const SKIP_MESSAGE =
  "Clerk E2E credentials are not configured (CLERK_SECRET_KEY, NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, E2E_CLERK_USER_EMAIL, E2E_CLERK_USER_PASSWORD). Skipping the authenticated suite.";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

setup(
  "Clerk global setup: provision test user, org and storage state",
  async ({ page }) => {
    if (!CLERK_TEST_CONFIGURED) {
      mkdirSync(path.dirname(storageStateFile), { recursive: true });
      writeFileSync(storageStateFile, JSON.stringify({}));
      setup.skip(true, SKIP_MESSAGE);
      return;
    }

    await clerkSetup();

    const email = requireEnv("E2E_CLERK_USER_EMAIL");
    const password = requireEnv("E2E_CLERK_USER_PASSWORD");

    const client = createClerkClient({
      secretKey: requireEnv("CLERK_SECRET_KEY"),
    });

    const users = (await client.users.getUserList({ emailAddress: [email] }))
      .data;

    const userId =
      users.length > 0
        ? users[0].id
        : (
            await client.users.createUser({
              emailAddress: [email],
              password,
            })
          ).id;

    if (users.length > 0) {
      await client.users.updateUser(userId, { password });
    }

    const orgs = (
      await client.organizations.getOrganizationList({ query: ORG_NAME })
    ).data;
    const org =
      orgs.find((candidate) => candidate.name === ORG_NAME) ??
      (await client.organizations.createOrganization({
        name: ORG_NAME,
        createdBy: userId,
      }));

    const memberships = (
      await client.users.getOrganizationMembershipList({ userId })
    ).data;
    if (
      !memberships.some((membership) => membership.organization.id === org.id)
    ) {
      await client.organizations.createOrganizationMembership({
        organizationId: org.id,
        userId,
        role: "admin",
      });
    }

    await page.goto("/");
    await clerk.signIn({ page, emailAddress: email });

    await page.evaluate(async (organizationId) => {
      await (window as any).Clerk.organization.setActive({ organizationId });
    }, org.id);

    await page.goto("/chat");
    await page.waitForURL("**/chat");

    await page.context().storageState({ path: storageStateFile });
  }
);
