import { expect, test } from "@playwright/test";

const CLERK_TEST_CONFIGURED = Boolean(
  process.env.CLERK_SECRET_KEY &&
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
    process.env.E2E_CLERK_USER_EMAIL &&
    process.env.E2E_CLERK_USER_PASSWORD
);

const SKIP_MESSAGE =
  "Clerk E2E credentials are not configured (CLERK_SECRET_KEY, NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, E2E_CLERK_USER_EMAIL, E2E_CLERK_USER_PASSWORD). Skipping the authenticated suite.";

test.describe("Signed-in chat", () => {
  test("chat UI mounts for a signed-in organization user", async ({ page }) => {
    // biome-ignore lint/suspicious/noSkippedTests: Intentional — skips the authenticated suite when Clerk E2E credentials are absent.
    test.skip(!CLERK_TEST_CONFIGURED, SKIP_MESSAGE);

    await page.goto("/chat");

    await expect(page).toHaveURL(/\/chat/);
    await expect(
      page.getByRole("link", { name: "Nuevo Agente" })
    ).toBeAttached();

    await page.goto("/agent-sessions/new");

    const cuitInput = page.getByPlaceholder("20123456789");
    await expect(cuitInput).toBeVisible();
    await expect(cuitInput).toBeEnabled();
  });
});
