import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

// Each run seeds its own tenant and synthetic users (seed_demo.py --tag), so the owner's demo
// tenant is never touched and runs can repeat.
export default function globalSetup(): void {
  const root = path.resolve(import.meta.dirname, "..", "..");
  const tag = `e2e${Date.now().toString(36)}`;
  // The run's files go to the system temporary folder, never into play-files/ (review, minor).
  const files = path.join(os.tmpdir(), `matchdesk-${tag}`);
  execFileSync(path.join(root, "backend/.venv/bin/python"), [path.join(root, "backend/scripts/seed_demo.py"), "--tag", tag, "--files-dir", files], {
    cwd: path.join(root, "backend"),
    stdio: "inherit",
  });
  writeFileSync(path.join(import.meta.dirname, ".run.json"), JSON.stringify({ tag, files }));
}
