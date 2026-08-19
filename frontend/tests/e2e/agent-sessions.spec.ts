import { expect, test } from "@playwright/test";

const CLERK_TEST_CONFIGURED = Boolean(
  process.env.CLERK_SECRET_KEY &&
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
    process.env.E2E_CLERK_USER_EMAIL &&
    process.env.E2E_CLERK_USER_PASSWORD
);

const SKIP_MESSAGE =
  "Clerk E2E credentials are not configured (CLERK_SECRET_KEY, NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, E2E_CLERK_USER_EMAIL, E2E_CLERK_USER_PASSWORD). Skipping the authenticated suite.";

test.describe("Agent sessions page", () => {
  test("persisted telemetry survives a reload (AST-6)", async ({ page }) => {
    // biome-ignore lint/suspicious/noSkippedTests: Intentional — skips the authenticated suite when Clerk E2E credentials are absent.
    test.skip(!CLERK_TEST_CONFIGURED, SKIP_MESSAGE);

    // Run a consultaarca chat first, then reload the dashboard: the table must
    // render persisted rows from /api/agent-sessions (BFF) instead of the
    // empty state — proving the page consumes the backend telemetry (AST-6).
    await page.goto("/agent-sessions/new");

    const cuitInput = page.getByPlaceholder("20123456789");
    await expect(cuitInput).toBeEnabled();

    // Kick off a report so the backend persists an agent_sessions row.
    await cuitInput.fill("20123456789");
    await page.getByRole("button", { name: /consultar|consultaarca/i }).click();

    // The live stream reports back into the monitor; we only need the row to
    // land in Postgres, then a clean reload exercises the persisted path.
    await page.waitForTimeout(2_000);

    await page.goto("/agent-sessions");
    await expect(page.getByRole("heading", { name: "Agent Sessions" })).toBeVisible();

    // A persisted consultaarca run renders an "Acciones" cell with the
    // canonical 7-task summary ("7 · …") instead of the empty state.
    await expect(page.getByText(/\d+ · /).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("No agent sessions captured yet")).toHaveCount(0);
  });
});