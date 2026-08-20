import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

/**
 * Landing light-theme scoping (LLT-1, LLT-2).
 *
 * The root ThemeProvider was removed from `app/layout.tsx` and scoped to
 * `app/(chat)/layout.tsx`. These specs prove the landing never receives a
 * `.dark` class — neither from a root provider (it no longer exists), nor
 * from a stored/system dark preference, nor at any point during load.
 *
 * Matches the `e2e` project: /e2e\/.*.test.ts/ (public, no auth needed).
 */

const DARK_CLASS_SEEN_FLAG = "__landingDarkSeen";

/** Luminance of the light `:root --background` token (oklch(0.985 0 0)). */
const LIGHT_BACKGROUND_LUMINANCE_THRESHOLD = 0.9;

function htmlDarkState(page: Page) {
  return page.evaluate(() => ({
    htmlHasDark: document.documentElement.classList.contains("dark"),
    darkElementCount: document.querySelectorAll(".dark").length,
  }));
}

/**
 * Relative luminance of the body background (0..1).
 *
 * Chromium serializes computed custom-property colors in their native color
 * space: the light `--background` token (oklch(0.985 0 0)) comes back as
 * `lab(98.26 0 0)` (Lab L in 0..100) — NOT as rgb(). Treating Lab L as an
 * sRGB channel produced 98.26*0.2126/255 ≈ 0.082, which is why the original
 * rgb-only parser failed a light background. Both lab() and oklch() expose a
 * perceptually-uniform L that works directly as the luminance proxy; rgb()
 * falls back to the sRGB-weighted formula.
 */
function bodyBackgroundLuminance(page: Page) {
  return page.evaluate(() => {
    const backgroundColor = getComputedStyle(document.body).backgroundColor;
    const lab = backgroundColor.match(/^lab\(\s*([\d.]+)/i);
    if (lab) {
      return Number(lab[1]) / 100;
    }
    const oklch = backgroundColor.match(/^oklch\(\s*([\d.]+)/i);
    if (oklch) {
      const l = Number(oklch[1]);
      return l > 1 ? l / 100 : l;
    }
    const channels = backgroundColor.match(/\d+(?:\.\d+)?/g)?.map(Number);
    if (!channels || channels.length < 3) {
      throw new Error(`Unexpected backgroundColor: ${backgroundColor}`);
    }
    const [r, g, b] = channels;
    return (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255;
  });
}

test.describe("Landing light theme scoping", () => {
  test("landing renders light on a dark OS, even with a stored dark theme (LLT-1)", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    // A stored dark theme must not leak into the landing either: without a
    // ThemeProvider on this route, nothing ever reads/ applies it.
    await page.addInitScript(() => {
      try {
        localStorage.setItem("theme", "dark");
      } catch {
        // Storage unavailable in the init context — the class assertions below
        // still fully apply.
      }
    });

    await page.goto("/");
    await expect(page.locator("main")).toBeVisible();

    const state = await htmlDarkState(page);
    expect(state.htmlHasDark).toBe(false);
    expect(state.darkElementCount).toBe(0);

    const luminance = await bodyBackgroundLuminance(page);
    expect(luminance).toBeGreaterThan(LIGHT_BACKGROUND_LUMINANCE_THRESHOLD);
  });

  test("landing renders light on a light OS (LLT-1)", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    await expect(page.locator("main")).toBeVisible();

    const state = await htmlDarkState(page);
    expect(state.htmlHasDark).toBe(false);
    expect(state.darkElementCount).toBe(0);

    const luminance = await bodyBackgroundLuminance(page);
    expect(luminance).toBeGreaterThan(LIGHT_BACKGROUND_LUMINANCE_THRESHOLD);
  });

  test("landing never receives a dark class during load on a dark OS (LLT-2)", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    // Watch the <html> class list from document start: any code path that
    // adds `.dark` during parse, hydration, or post-hydration is recorded.
    await page.addInitScript((flag) => {
      (window as unknown as Record<string, unknown>)[flag] = false;
      const html = document.documentElement;
      const check = () => {
        if (html.classList.contains("dark")) {
          (window as unknown as Record<string, unknown>)[flag] = true;
        }
      };
      check();
      new MutationObserver(check).observe(html, {
        attributes: true,
        attributeFilter: ["class"],
      });
    }, DARK_CLASS_SEEN_FLAG);

    await page.goto("/");
    await expect(page.locator("main")).toBeVisible();
    await page.waitForLoadState("load");
    // Settle window after hydration so late client effects are observed.
    await page.waitForTimeout(300);

    const seenDark = await page.evaluate(
      (flag) => (window as unknown as Record<string, boolean>)[flag],
      DARK_CLASS_SEEN_FLAG
    );
    expect(seenDark).toBe(false);

    const state = await htmlDarkState(page);
    expect(state.htmlHasDark).toBe(false);
    expect(state.darkElementCount).toBe(0);
  });
});
