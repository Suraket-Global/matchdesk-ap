import { readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { stack } from "../e2e/stack";

export default function teardown(): void {
  stack("down");
  try {
    const { files } = JSON.parse(readFileSync(path.join(import.meta.dirname, ".run.json"), "utf8")) as { files: string };
    rmSync(files, { recursive: true, force: true });
  } catch {
    /* nothing to clean */
  }
}
