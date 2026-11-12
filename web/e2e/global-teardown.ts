import { readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { changed, counts, stack } from "./stack";

// Drops matchdesk_e2e and stops its API and worker, removes the run's temporary play files, then
// fails the run if any table of matchdesk_dev (auth_rate_events included) changed its row count.
export default function globalTeardown(): void {
  const run = JSON.parse(readFileSync(path.join(import.meta.dirname, ".run.json"), "utf8")) as {
    files: string;
    dev: Record<string, number>;
  };
  stack("down");
  rmSync(run.files, { recursive: true, force: true });
  const diff = changed(run.dev, counts("matchdesk_dev"));
  if (diff.length) throw new Error(`Playwright changed matchdesk_dev: ${diff.join("; ")}`);
  console.log("matchdesk_dev unchanged by this run (row counts of every table, auth_rate_events included)");
}
