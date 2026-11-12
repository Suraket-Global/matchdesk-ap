import { mkdtempSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { stack } from "../e2e/stack";

export default function setup(): void {
  const files = mkdtempSync(path.join(os.tmpdir(), "matchdesk-shots-"));
  stack("up");
  stack("seed", "--preload", "--files-dir", files);
  writeFileSync(path.join(import.meta.dirname, ".run.json"), JSON.stringify({ files }));
}
