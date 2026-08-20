import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

/**
 * Chat theme toggle with landing scoping (LLT-3).
 *
 * The ThemeProvider now lives in `app/(chat)/layout.tsx` only. These specs
 * prove the toggle keeps working inside the chat shell and that toggling dark
 * in chat never leaks a `.dark` class into the landing on revisit.
 *
 * Matches the `signed-in` project: /e2e\/.*\.signedin\.spec\.ts/ — the toggle
 * lives in the sidebar user nav, which requires a signed-in user.
 */

const CLERK_TEST_CONFIGURED = Boolean(
  process.env.CLERK_SECRET_KEY &&
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
    process.env.E2E_CLERK_USER_EMAIL &&
    process.env.E2E_CLERK_USER_PASSWORD
);

const SKIP_MESSAGE =
  "Clerk E2E credentials are not configured (CLERK_SECRET_KEY, NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, E2E_CLERK_USER_EMAIL, E2E_CLERK_USER_PASSWORD). Skipping the authenticated suite.";

/** Clear any stored theme so each test starts from the system default. */
async function startFromSystemDefault(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.removeItem("theme");
    } catch {
      // Storage unavailable in the init context — the class assertions below
      // still fully apply.
    }
  });
}

function htmlHasDark(page: Page): Promise<boolean> {
  return page.evaluate(() =>
    document.documentElement.classList.contains("dark")
  );
}

test.describe("Chat theme toggle scoped to the chat layout", () => {
  test("toggle to dark renders chat dark; landing stays light on revisit (LLT-3)", async ({
    page,
  }) => {
    // biome-ignore lint/suspicious/noSkippedTests: Intentional — skips the authenticated suite when Clerk E2E credentials are absent.
    test.skip(!CLERK_TEST_CONFIGURED, SKIP_MESSAGE);

    await startFromSystemDefault(page);
    await page.goto("/chat");

    // The toggle lives in the sidebar user nav, rendered once Clerk loads.
    const userNavButton = page.getByTestId("user-nav-button");
    await expect(userNavButton).toBeVisible();

    // Toggle light → dark.
    await userNavButton.click();
    const themeItem = page.getByTestId("user-nav-item-theme");
    await expect(themeItem).toBeVisible();
    await themeItem.click();

    await expect.poll(() => htmlHasDark(page)).toBe(true);

    // Revisit the landing: it must remain light although the stored theme is
    // now dark — the landing has no ThemeProvider to apply it.
    await page.goto("/");
    await expect(page.locator("main")).toBeVisible();
    const landing = await page.evaluate(() => ({
      htmlHasDark: document.documentElement.classList.contains("dark"),
      darkElementCount: document.querySelectorAll(".dark").length,
    }));
    expect(landing.htmlHasDark).toBe(false);
    expect(landing.darkElementCount).toBe(0);
  });

  test("toggle back to light removes dark from the chat (LLT-3)", async ({
    page,
  }) => {
    // biome-ignore lint/suspicious/noSkippedTests: Intentional — skips the authenticated suite when Clerk E2E credentials are absent.
    test.skip(!CLERK_TEST_CONFIGURED, SKIP_MESSAGE);

    await startFromSystemDefault(page);
    await page.goto("/chat");

    const userNavButton = page.getByTestId("user-nav-button");
    await expect(userNavButton).toBeVisible();

    // Force dark first, then toggle back to light.
    await userNavButton.click();
    const themeItem = page.getByTestId("user-nav-item-theme");
    await expect(themeItem).toBeVisible();
    await themeItem.click();
    await expect.poll(() => htmlHasDark(page)).toBe(true);

    await userNavButton.click();
    await expect(themeItem).toBeVisible();
    await themeItem.click();
    await expect.poll(() => htmlHasDark(page)).toBe(false);
  });
});
