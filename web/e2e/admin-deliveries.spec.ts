import { expect, test } from "@playwright/test";
import { clearCart, login, orderNumberFromUrl, simulatePayment } from "./helpers";

// 005 US1: a paid order shows up as waiting in Deliveries; the admin assigns the seeded rider.
test.describe("005 admin deliveries", () => {
  test.beforeEach(async ({ context }) => {
    await context.addCookies([{ name: "sa_lang", value: "en", url: "http://localhost:3100" }]);
  });

  test("a paid order waits for a rider, and the admin assigns one", async ({ page }) => {
    await clearCart(page);
    await page.goto("/products/e2e-thermos-flask");
    await page.getByRole("button", { name: "Add to cart" }).click();
    await expect(page.getByTestId("cart-count")).toHaveText("1");
    await page.goto("/checkout");
    await page.getByLabel("Full name").fill("Delivery Flow");
    await page.getByLabel("Phone number").fill("0713 555 777");
    await page.getByLabel("Region").selectOption("Dar es Salaam");
    await page.getByLabel("Street / area / landmark").fill("Mwenge, near TRA");
    await page.getByRole("button", { name: "Place order" }).click();
    await expect(page).toHaveURL(/\/orders\/[A-Z0-9]+/);
    const number = orderNumberFromUrl(page.url());
    await simulatePayment(number);
    await expect(page.getByTestId("order-status")).toHaveText("Paid", { timeout: 15_000 });

    await login(page, "e2e_admin");
    await expect(page).toHaveURL(/\/admin$/);
    await page.goto("/admin/deliveries?status=waiting");
    const row = page.getByTestId("delivery-row").filter({ hasText: number });
    await expect(row).toContainText("Waiting for a rider");
    await row.getByRole("link", { name: number }).click();

    await expect(page.getByTestId("delivery-status")).toHaveText("Waiting for a rider");
    await page.getByRole("button", { name: "Assign rider" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("radio", { name: /Rider Juma/ }).check();
    await dialog.getByRole("button", { name: "Assign", exact: true }).click();

    await expect(page.getByTestId("delivery-status")).toHaveText("Assigned");
    await expect(page.getByTestId("delivery-rider")).toHaveText("Rider Juma");
    await expect(page.getByTestId("delivery-history")).toContainText("admin");

    // the order followed the delivery
    await page.getByRole("link", { name: number }).first().click();
    await expect(page.getByTestId("admin-order-status")).toHaveText("Processing");
    await expect(page.getByRole("link", { name: "Open delivery" })).toBeVisible();
  });
});
