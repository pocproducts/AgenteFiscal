import { expect, test } from "@playwright/test";

test.describe("Authentication Pages", () => {
  test("login page renders correctly", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByPlaceholder("tu@email.com")).toBeVisible();
    await expect(page.getByLabel("Contraseña")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Iniciar sesión" })
    ).toBeVisible();
    await expect(page.getByText("¿No tienes cuenta?")).toBeVisible();
  });

  test("register page renders correctly", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByPlaceholder("tu@email.com")).toBeVisible();
    await expect(page.getByLabel("Contraseña")).toBeVisible();
    await expect(page.getByRole("button", { name: "Registrarse" })).toBeVisible();
    await expect(page.getByText("¿Ya tienes una cuenta?")).toBeVisible();
  });

  test("can navigate from login to register", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("link", { name: "Registrarse" }).click();
    await expect(page).toHaveURL("/register");
  });

  test("can navigate from register to login", async ({ page }) => {
    await page.goto("/register");
    await page.getByRole("link", { name: "Iniciar sesión" }).click();
    await expect(page).toHaveURL("/login");
  });
});
