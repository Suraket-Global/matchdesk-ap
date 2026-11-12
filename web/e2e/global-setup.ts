import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import path from "node:path";

// Each run seeds its own tenant and synthetic users (seed_demo.py --tag), so the owner's demo
// tenant is never touched and runs can repeat.
export default function globalSetup(): void {
  const root = path.resolve(import.meta.dirname, "..", "..");
  const tag = `e2e${Date.now().toString(36)}`;
  execFileSync(path.join(root, "backend/.venv/bin/python"), [path.join(root, "backend/scripts/seed_demo.py"), "--tag", tag], {
    cwd: path.join(root, "backend"),
    stdio: "inherit",
  });
  writeFileSync(path.join(import.meta.dirname, ".run.json"), JSON.stringify({ tag, files: path.join(root, "play-files", tag) }));
}
