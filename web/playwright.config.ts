import { defineConfig, devices } from "@playwright/test";

/**
 * Isolated e2e stack (does not touch dev servers on :8000/:3000):
 *   fake Stakaba :8765  →  Django :8001 (test Postgres on :5434, eager Celery)  →  Next :3100
 * Requires the test DB container from the 001 setup (see specs/002-web-storefront/quickstart.md).
 */
const DB = process.env.E2E_DATABASE_URL ?? "postgres://shop:shop@localhost:5434/shop";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3100",
    trace: "retain-on-failure",
  },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "node e2e/fake-stakaba.mjs",
      url: "http://127.0.0.1:8765/_e2e/payments",
      reuseExistingServer: false,
    },
    {
      command: "node e2e/start-backend.mjs",
      url: "http://127.0.0.1:8001/api/delivery-regions/",
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: DB,
        DEBUG: "True",
        STAKABA_API_KEY: "sk_test_e2e",
        STAKABA_BASE_URL: "http://127.0.0.1:8765",
        STAKABA_WEBHOOK_TOKEN: "e2e-webhook-token",
        STAKABA_CONFIRM_VIA_API: "False",
        CELERY_TASK_ALWAYS_EAGER: "True",
        ALLOWED_HOSTS: "localhost,127.0.0.1",
      },
    },
    {
      command: "npx next dev --port 3100",
      url: "http://localhost:3100",
      timeout: 180_000,
      reuseExistingServer: false,
      env: { DJANGO_API_URL: "http://127.0.0.1:8001", NEXT_DIST_DIR: ".next-e2e" },
    },
  ],
});
