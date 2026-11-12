import { execFileSync } from "node:child_process";
import path from "node:path";

// B6 (outside QA finding 2): Playwright runs on its own stack: database matchdesk_e2e, API on 8102,
// its own worker and file folder, the web dev server on 5174. The dev database is never written.
export const ROOT = path.resolve(import.meta.dirname, "..", "..");
export const E2E_WEB = "http://127.0.0.1:5174";
export const E2E_API = "http://127.0.0.1:8102";
const STACK = path.join(ROOT, "backend/scripts/e2e_stack.sh");

export function stack(...args: string[]): void {
  execFileSync(STACK, args, { cwd: path.join(ROOT, "backend"), stdio: "inherit" });
}

/** Row counts of every table of a local database (backend/scripts/db_counts.py). */
export function counts(db: string): Record<string, number> {
  const out = execFileSync(path.join(ROOT, "backend/.venv/bin/python"), [path.join(ROOT, "backend/scripts/db_counts.py"), db], {
    cwd: path.join(ROOT, "backend"),
  });
  return JSON.parse(out.toString()) as Record<string, number>;
}

/** Tables whose row count differs between two snapshots, as "table: before -> after". */
export function changed(before: Record<string, number>, after: Record<string, number>): string[] {
  const names = new Set([...Object.keys(before), ...Object.keys(after)]);
  return [...names].filter((t) => before[t] !== after[t]).map((t) => `${t}: ${before[t] ?? "absent"} -> ${after[t] ?? "absent"}`);
}
