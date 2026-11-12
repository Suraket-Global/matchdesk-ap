import { readFileSync, rmSync } from "node:fs";
import path from "node:path";

// The run's play files are temporary; its synthetic tenant stays in the dev database (make demo-reset clears it).
export default function globalTeardown(): void {
  try {
    const { files } = JSON.parse(readFileSync(path.join(import.meta.dirname, ".run.json"), "utf8"));
    rmSync(files, { recursive: true, force: true });
  } catch {
    /* nothing to clean */
  }
}
