import { expect, test, type Page } from "@playwright/test";
import { clearCart, login, orderNumberFromUrl, simulatePayment } from "./helpers";

// 1×1 PNG; Django's ImageField runs it through Pillow, so it must be a real image.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);
const stamp = () => `${Date.now()}`.slice(-7);

async function loginAdmin(page: Page) {
  await login(page, "e2e_admin");
  await expect(page).toHaveURL(/\/admin$/);
}

async function placePaidOrder(page: Page) {
  await clearCart(page);
  await page.goto("/products/e2e-red-sneakers");
  await page.getByRole("button", { name: "Add to cart" }).click();
  await expect(page.getByTestId("cart-count")).toHaveText("1");
  await page.goto("/checkout");
  await page.getByLabel("Full name").fill("Admin Flow");
  await page.getByLabel("Phone number").fill("0713 555 444");
  await page.getByLabel("Region").selectOption("Dar es Salaam");
  await page.getByLabel("Street / area / landmark").fill("Kariakoo");
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page).toHaveURL(/\/orders\/[A-Z0-9]+/);
  const number = orderNumberFromUrl(page.url());
  await simulatePayment(number);
  await expect(page.getByTestId("order-status")).toHaveText("Paid", { timeout: 15_000 });
  return number;
}

test.describe("US3 admin", () => {
  test.beforeEach(async ({ context }) => {
    await context.addCookies([{ name: "sa_lang", value: "en", url: "http://localhost:3100" }]);
  });

  test("customers are forbidden and anonymous users must log in", async ({ page }) => {
    await page.goto("/admin/orders");
    await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Forders/);

    await login(page, "e2e_customer");
    await expect(page).toHaveURL(/\/account/);
    for (const path of ["/admin", "/admin/products", "/admin/orders"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/forbidden$/);
    }
  });

  test("product create with images, then deactivate hides it from the shop", async ({ page }) => {
    await loginAdmin(page);
    const id = stamp();
    const name = `E2E Lamp ${id}`;

    await page.goto("/admin/products/new");
    await page.getByLabel("Name", { exact: true }).fill(name);
    await page.getByLabel("SKU").fill(`LAMP-${id}`);
    await page.getByLabel("Category").selectOption({ label: "Shoes" });
    await page.getByLabel("Price (TSh)").fill("12000");
    await page.getByLabel("Compare-at price").fill("9000");
    await page.getByLabel("Stock", { exact: true }).fill("5");
    await page.getByLabel("Images", { exact: true }).setInputFiles([
      { name: "a.png", mimeType: "image/png", buffer: PNG },
      { name: "b.png", mimeType: "image/png", buffer: PNG },
    ]);
    await page.getByRole("button", { name: "Create product" }).click();
    await expect(page.getByText("Compare-at price must be higher than the price.")).toBeVisible();
    await page.getByLabel("Compare-at price").fill("15000");
    await page.getByRole("button", { name: "Create product" }).click();

    await expect(page).toHaveURL(/\/admin\/products\/e2e-lamp-/);
    const slug = new URL(page.url()).pathname.split("/").pop()!;
    await expect(page.getByRole("img", { name: name })).toHaveCount(2);

    await page.goto(`/products/${slug}`);
    await expect(page.getByRole("heading", { name })).toBeVisible();

    await page.goto(`/admin/products/${slug}`);
    await page.getByLabel("Active (visible in the shop)").uncheck();
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Product saved")).toBeVisible();

    // The page streams inside Suspense, so Next sends 200 with the not-found UI (and noindex).
    await page.goto(`/products/${slug}`);
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  });

  test("order status change records the note; invalid transitions are refused", async ({ page }) => {
    await page.goto("/");
    const number = await placePaidOrder(page);
    await loginAdmin(page);

    await page.goto(`/admin/orders?search=${number}`);
    await page.getByRole("link", { name: number }).click();
    await expect(page.getByTestId("admin-order-status")).toHaveText("Paid");

    await page.getByRole("button", { name: "Change status" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel("New status").selectOption("processing");
    await dialog.getByLabel("Note").fill("Packed at warehouse");
    await dialog.getByRole("button", { name: "Update status" }).click();
    await expect(page.getByTestId("admin-order-status")).toHaveText("Processing");
    await expect(page.locator("main").getByText("Packed at warehouse")).toBeVisible();

    await page.getByRole("button", { name: "Change status" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("New status").selectOption("delivered");
    await dialog.getByRole("button", { name: "Update status" }).click();
    await expect(dialog.getByRole("alert")).toContainText(/Cannot move an order/);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByTestId("admin-order-status")).toHaveText("Processing");
  });

  test("a new delivery region shows in checkout", async ({ page }) => {
    await loginAdmin(page);
    const region = `E2E Region ${stamp()}`;
    await page.goto("/admin/delivery-regions");
    await page.getByRole("button", { name: "Add region" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill(region);
    await dialog.getByLabel("Fee (TSh)").fill("4500");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("cell", { name: region, exact: true })).toBeVisible();

    await clearCart(page);
    await page.goto("/products/e2e-wooden-spoons");
    await page.getByRole("button", { name: "Add to cart" }).click();
    await expect(page.getByTestId("cart-count")).toHaveText("1");
    await page.goto("/checkout");
    await expect(page.getByLabel("Region").locator("option", { hasText: region })).toHaveCount(1);
  });
});
