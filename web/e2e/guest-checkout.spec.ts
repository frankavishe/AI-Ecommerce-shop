import { expect, test } from "@playwright/test";
import { clearCart, orderNumberFromUrl, simulatePayment } from "./helpers";

test.describe("US1 guest buys a product", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.addCookies([{ name: "sa_lang", value: "en", url: "http://localhost:3100" }]);
    await page.goto("/");
    await clearCart(page);
  });

  test("home shows categories and products", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Shoes" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: /Red Sneakers/ }).first()).toBeVisible();
    await expect(page.getByText("TSh 45,000").first()).toBeVisible();
  });

  test("search and category filter update the URL and results", async ({ page }) => {
    await page.goto("/products");
    await page.getByRole("searchbox", { name: "Search" }).first().fill("sneakers");
    await page.getByRole("searchbox", { name: "Search" }).first().press("Enter");
    await expect(page).toHaveURL(/search=sneakers/);
    await expect(page.locator('a[href="/products/e2e-red-sneakers"]')).toBeVisible();
    await expect(page.locator('a[href="/products/e2e-cooking-pot"]')).toHaveCount(0);

    await page.goto("/products?category=e2e-kitchen");
    await expect(page.locator('a[href="/products/e2e-cooking-pot"]')).toBeVisible();
    await expect(page.locator('a[href="/products/e2e-red-sneakers"]')).toHaveCount(0);
  });

  test("out-of-stock product cannot be added", async ({ page }) => {
    await page.goto("/products/e2e-sold-out-kettle");
    await expect(page.getByText("Out of stock").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Add to cart" })).toBeDisabled();
  });

  test("cart persists across reloads and shows the server's stock message", async ({ page }) => {
    await page.goto("/products/e2e-wooden-spoons");
    await page.getByRole("button", { name: "Add to cart" }).click();
    await expect(page.getByTestId("cart-count")).toHaveText("1");
    await page.reload();
    await expect(page.getByTestId("cart-count")).toHaveText("1");

    await page.goto("/cart");
    const qty = page.getByRole("spinbutton", { name: /Quantity/ });
    await qty.fill("9");
    await qty.press("Enter");
    // Only 2 in stock: the server refuses and the cart keeps its quantity.
    await expect(page.getByText(/only|stock/i).first()).toBeVisible();
    await expect(qty).toHaveValue("1");
  });

  test("mobile money checkout shows the order and flips to paid", async ({ page }) => {
    await page.goto("/products/e2e-red-sneakers");
    await page.getByRole("button", { name: "Add to cart" }).click();
    await expect(page.getByTestId("cart-count")).toHaveText("1");
    await page.goto("/checkout");

    await page.getByLabel("Full name").fill("Juma Hamisi");
    await page.getByLabel("Phone number").fill("0712 000 111");
    await page.getByLabel("Region").selectOption("Dar es Salaam");
    await page.getByLabel(/Street/).fill("Mikocheni B, near the market");
    await expect(page.getByTestId("checkout-total")).toHaveText("TSh 48,000");

    // Invalid phone first: field error, nothing placed.
    await page.getByLabel("Phone number").fill("12345");
    await page.getByRole("button", { name: "Place order" }).click();
    await expect(page.getByText(/Enter a Tanzanian mobile number/)).toBeVisible();
    await expect(page).toHaveURL(/\/checkout/);

    await page.getByLabel("Phone number").fill("0712 000 111");
    await page.getByRole("button", { name: "Place order" }).click();
    await expect(page).toHaveURL(/\/orders\/[A-Z0-9]+/);
    await expect(page.getByText(/enter your mobile money PIN/)).toBeVisible();
    await expect(page.getByTestId("order-status")).toHaveText("Awaiting payment");
    await expect(page.getByTestId("cart-count")).toHaveCount(0);

    await simulatePayment(orderNumberFromUrl(page.url()));
    await expect(page.getByTestId("order-status")).toHaveText("Paid", { timeout: 10_000 });
  });

  test("card needs an email, then redirects to the hosted page", async ({ page }) => {
    await page.goto("/products/e2e-thermos-flask");
    await page.getByRole("button", { name: "Add to cart" }).click();
    await expect(page.getByTestId("cart-count")).toHaveText("1");
    await page.goto("/checkout");
    await page.getByLabel("Full name").fill("Neema Said");
    await page.getByLabel("Phone number").fill("0754 222 333");
    await page.getByLabel("Region").selectOption("Arusha");
    await page.getByLabel(/Street/).fill("Njiro");
    await page.getByLabel("Card").check();
    await page.getByRole("button", { name: "Place order" }).click();
    await expect(page.getByText("An email address is needed to pay by card.")).toBeVisible();

    await page.getByLabel("Email").fill("neema@example.com");
    await page.getByRole("button", { name: "Place order" }).click();
    await page.waitForURL(/e2e-fake-card\?ref=FAKECARD/);
  });

  test("at 360 px the cart name clears the quantity box and the page does not scroll sideways", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await page.goto("/products/e2e-red-sneakers");
    await page.getByRole("button", { name: "Add to cart" }).click();
    await expect(page.getByTestId("cart-count")).toHaveText("1");
    await page.goto("/cart");

    const line = page.getByTestId("cart-line").first();
    await expect(line).toBeVisible();
    const name = (await line.getByRole("link").first().boundingBox())!;
    const quantity = (await line.locator("input").boundingBox())!;
    expect(name.y + name.height).toBeLessThanOrEqual(quantity.y);

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBe(0);
  });

  test("switching to Swahili changes the interface", async ({ page }) => {
    await page.goto("/products/e2e-red-sneakers");
    await page.getByRole("button", { name: /Language/ }).click();
    await expect(page.getByRole("button", { name: "Weka kwenye kikapu" })).toBeVisible();
    await expect(page.getByText("Viatu vyekundu vya michezo.")).toBeVisible();
    await page.goto("/checkout");
    await expect(page.getByRole("heading", { name: /Kulipia|Kikapu chako/ })).toBeVisible();
  });
});
