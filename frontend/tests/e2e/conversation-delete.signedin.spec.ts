import { expect, test } from "@playwright/test";

const CLERK_TEST_CONFIGURED = Boolean(
  process.env.CLERK_SECRET_KEY &&
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY &&
    process.env.E2E_CLERK_USER_EMAIL &&
    process.env.E2E_CLERK_USER_PASSWORD
);

const SKIP_MESSAGE =
  "Clerk E2E credentials are not configured (CLERK_SECRET_KEY, NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, E2E_CLERK_USER_EMAIL, E2E_CLERK_USER_PASSWORD). Skipping the authenticated suite.";

test.describe("Conversation deletion", () => {
  test("BFF propagates a backend 404 as deleted:false, never success (CD-3)", async ({
    page,
  }) => {
    // biome-ignore lint/suspicious/noSkippedTests: Intentional — skips the authenticated suite when Clerk E2E credentials are absent.
    test.skip(!CLERK_TEST_CONFIGURED, SKIP_MESSAGE);

    await page.goto("/chat");

    // An id that never existed: the backend 404s it and the BFF must NOT
    // swallow that as a successful no-op (the old bug). The honest envelope
    // keeps the sidebar from hiding a row the server never deleted.
    const res = await page.request.delete(
      `/api/chat?id=${crypto.randomUUID()}`
    );
    expect(res.status()).toBe(404);

    const body = (await res.json()) as {
      success?: boolean;
      deleted?: boolean;
    };
    expect(body.success).toBe(false);
    expect(body.deleted).toBe(false);
  });

  test("deleting the active chat navigates away and removes the row (CD-4)", async ({
    page,
  }) => {
    // biome-ignore lint/suspicious/noSkippedTests: Intentional — skips the authenticated suite when Clerk E2E credentials are absent.
    test.skip(!CLERK_TEST_CONFIGURED, SKIP_MESSAGE);

    // Run a consultaarca chat so the backend owns a real conversation row.
    await page.goto("/agent-sessions/new");

    const cuitInput = page.getByPlaceholder("20123456789");
    await expect(cuitInput).toBeEnabled();
    await cuitInput.fill("20123456789");
    await page.getByRole("button", { name: /consultar|consultaarca/i }).click();

    // The run persists the conversation; the sidebar history row is a link to
    // /chat/{id}. Newest first, so the first link is the chat we just created.
    const chatLink = page.locator('a[href^="/chat/"]').first();
    await expect(chatLink).toBeAttached({ timeout: 60_000 });
    const chatUrl = await chatLink.getAttribute("href");
    expect(chatUrl).toBeTruthy();

    // Delete it from the row's kebab menu + confirm dialog.
    const row = chatLink.locator("xpath=ancestor::li");
    await row.getByRole("button", { name: /más|more/i }).click();
    await page.getByRole("menuitem", { name: /eliminar|delete/i }).click();
    await page.getByRole("button", { name: /continuar|continue/i }).click();

    // CD-4 success: the deleted chat was the active one → navigate to the app
    // Home, the row is gone from history, and a success toast confirms it.
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.locator(`a[href="${chatUrl}"]`)).toHaveCount(0);
    await expect(
      page.getByText(/chat eliminado|chat deleted/i).first()
    ).toBeAttached();
  });
});
