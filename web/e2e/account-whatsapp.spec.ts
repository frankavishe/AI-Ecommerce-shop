import { expect, test } from "@playwright/test";
import { sendWhatsAppText, uniqWaId } from "./whatsapp";

const uniq = () => `e2e_wa_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
const uniqPhone = () => `07${String(Date.now()).slice(-8)}`;

test.describe("US2 link WhatsApp from the account page", () => {
  test.beforeEach(async ({ context }) => {
    await context.addCookies([{ name: "sa_lang", value: "en", url: "http://localhost:3100" }]);
  });

  test("get a code, send it from WhatsApp, the card flips to linked, then unlink", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Username").fill(uniq());
    await page.getByLabel("Password").fill("secret-pass-9");
    await page.getByLabel("First name").fill("Neema");
    await page.getByLabel("Last name").fill("Mushi");
    await page.getByLabel("Phone number").fill(uniqPhone());
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/account$/);

    const card = page.getByTestId("whatsapp-card");
    await card.getByRole("button", { name: "Get link code" }).click();

    const codeText = card.getByTestId("whatsapp-code");
    await expect(codeText).toHaveText(/^LINK-[A-HJ-NP-Z2-9]{6}$/);
    const code = (await codeText.textContent())!.trim();
    await expect(card.getByText(/Expires in \d+:\d{2}/)).toBeVisible();
    await expect(card.getByRole("link", { name: "Open WhatsApp" })).toHaveAttribute(
      "href",
      `https://wa.me/255700000000?text=${code}`,
    );

    const waId = uniqWaId();
    await sendWhatsAppText(waId, `Habari ${code}`);

    // the card polls every 5 s while a code is shown
    await expect(card.getByText(`Linked to +${waId.slice(0, 3)} ${waId.slice(3, 6)} *** ${waId.slice(-3)}`)).toBeVisible({
      timeout: 15_000,
    });
    await expect(card.getByTestId("whatsapp-code")).toHaveCount(0);

    await card.getByRole("button", { name: "Unlink" }).click();
    await expect(card.getByText("Unlink this WhatsApp number?")).toBeVisible();
    await card.getByRole("button", { name: "Unlink" }).click();
    await expect(card.getByRole("button", { name: "Get link code" })).toBeVisible();
  });
});
