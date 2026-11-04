// Starts the isolated e2e Django: migrate → seed → runserver :8001. Env comes from playwright.config.ts.
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../backend");
const python = path.join(backend, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const run = (args) => {
  const r = spawnSync(python, ["manage.py", ...args], { cwd: backend, stdio: "inherit", env: process.env });
  if (r.status !== 0) process.exit(r.status ?? 1);
};

run(["migrate", "--noinput"]);
run(["shell", "-c", "exec(open('../web/e2e/seed.py', encoding='utf-8').read())"]);
const server = spawn(python, ["manage.py", "runserver", "127.0.0.1:8001", "--noreload"], {
  cwd: backend,
  stdio: "inherit",
  env: process.env,
});
const stop = () => server.kill();
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
server.on("exit", (code) => process.exit(code ?? 0));
