import { expect, test, type Page } from "@playwright/test";
import { clearCart, login, orderNumberFromUrl } from "./helpers";

const uniq = () => `e2e_u_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
/** Phones are unique per account, so each registration gets its own 07xx number. */
const uniqPhone = () => `07${String(Date.now()).slice(-8)}`;

async function addToCart(page: Page, slug: string) {
  await page.goto(`/products/${slug}`);
  await page.getByRole("button", { name: "Add to cart" }).click();
  await expect(page.getByTestId("cart-count")).toHaveText("1");
}

async function registerUser(page: Page, username: string, phone = uniqPhone()) {
  await page.goto("/register");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill("secret-pass-9");
  await page.getByLabel("First name").fill("Neema");
  await page.getByLabel("Last name").fill("Mushi");
  await page.getByLabel("Phone number").fill(phone);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/account$/);
}

async function placeGuestOrder(page: Page) {
  await addToCart(page, "e2e-red-sneakers");
  await page.goto("/checkout");
  await page.getByLabel("Full name").fill("Juma Hamisi");
  await page.getByLabel("Phone number").fill("0712 000 222");
  await page.getByLabel("Region").selectOption("Dar es Salaam");
  await page.getByLabel("Street / area / landmark").fill("Mikocheni B");
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(page).toHaveURL(/\/orders\/[A-Z0-9]+/);
  return orderNumberFromUrl(page.url());
}

test.describe("US2 registered customer and tracking", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.addCookies([{ name: "sa_lang", value: "en", url: "http://localhost:3100" }]);
    await page.goto("/");
    await clearCart(page);
  });

  test("registering keeps the guest cart", async ({ page }) => {
    await addToCart(page, "e2e-wooden-spoons");
    await registerUser(page, uniq());
    await expect(page.getByTestId("cart-count")).toHaveText("1");
  });

  test("saved address prefills checkout and the order shows in history; logout protects /account", async ({ page }) => {
    const phone = uniqPhone();
    await registerUser(page, uniq(), phone);

    await page.goto("/account/addresses");
    await page.getByRole("button", { name: "Add address" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Label").fill("Home");
    await dialog.getByLabel("Region").selectOption("Arusha");
    await dialog.getByLabel("Street / area / landmark").fill("Njiro Road 12");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Njiro Road 12")).toBeVisible();

    await addToCart(page, "e2e-red-sneakers");
    await page.goto("/checkout");
    await expect(page.getByLabel("Saved address")).toBeVisible();
    await expect(page.getByLabel("Full name")).toHaveValue("Neema Mushi");
    await expect(page.getByLabel("Phone number")).toHaveValue(`+255${phone.slice(1)}`);
    await page.getByRole("button", { name: "Place order" }).click();
    await expect(page).toHaveURL(/\/orders\/[A-Z0-9]+/);
    const number = orderNumberFromUrl(page.url());

    await page.goto("/account/orders");
    await expect(page.getByRole("link", { name: number })).toBeVisible();

    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.goto("/account");
    await expect(page).toHaveURL(/\/login\?next=%2Faccount/);
  });

  test("track finds an order with the right phone only", async ({ page, context }) => {
    const number = await placeGuestOrder(page);
    // A fresh tab has no guest proof, so tracking is the only way in.
    await context.clearCookies();
    const fresh = await context.newPage();

    await fresh.goto(`/track?number=${number}`);
    await expect(fresh.getByLabel("Order number")).toHaveValue(number);
    await fresh.getByLabel("Phone number").fill("0712 999 999");
    await fresh.getByRole("button", { name: "Find order" }).click();
    await expect(fresh.getByText("No order matches that number and phone.")).toBeVisible();

    await fresh.getByLabel("Phone number").fill("0712 000 222");
    await fresh.getByRole("button", { name: "Find order" }).click();
    await expect(fresh).toHaveURL(new RegExp(`/orders/${number}`));
    await expect(fresh.getByTestId("order-status")).toBeVisible();
  });

  test("a wrong password shows one generic error", async ({ page }) => {
    await login(page, "e2e_customer", "not-the-password");
    const alerts = page.locator("form [role=alert]");
    await expect(alerts).toHaveCount(1);
    await expect(alerts).toHaveText("Invalid username or password.");
    await expect(page).toHaveURL(/\/login/);
  });

  test("login returns to next", async ({ page }) => {
    await page.goto("/account/orders");
    await expect(page).toHaveURL(/\/login\?next=/);
    await page.getByLabel("Username").fill("e2e_customer");
    await page.getByLabel("Password").fill("e2e-pass-123");
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page).toHaveURL(/\/account\/orders$/);
  });
});
