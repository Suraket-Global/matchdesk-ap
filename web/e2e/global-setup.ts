import { writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { counts, stack } from "./stack";

// Each run gets a fresh matchdesk_e2e database and its own API and worker (e2e_stack.sh), seeds one
// tagged tenant there, and records the row counts of matchdesk_dev so the teardown can prove the
// run left the owner's demo database alone (B6, outside QA finding 2).
export default function globalSetup(): void {
  const tag = `e2e${Date.now().toString(36)}`;
  const files = path.join(os.tmpdir(), `matchdesk-${tag}`);
  const dev = counts("matchdesk_dev");
  stack("up");
  stack("seed", "--tag", tag, "--files-dir", files);
  writeFileSync(path.join(import.meta.dirname, ".run.json"), JSON.stringify({ tag, files, dev }));
}
