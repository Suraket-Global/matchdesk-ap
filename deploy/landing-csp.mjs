// B18: writes the nginx header line for the landing page's Content-Security-Policy. The landing page
// is one self-contained file with one inline <script> and one inline <style>; each is allowed by its
// SHA-256 hash, so no 'unsafe-inline' is needed for elements. Its six style="" attributes need
// 'unsafe-hashes' with their hashes. Fonts come from Google Fonts, as the page links them.
// Usage: node landing-csp.mjs landing/index.html > landing-csp.conf
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const html = readFileSync(process.argv[2], "utf8");
const hash = (s) => `'sha256-${createHash("sha256").update(s, "utf8").digest("base64")}'`;
const blocks = (tag) => [...html.matchAll(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`, "g"))].map((m) => m[1]);
const attrs = [...html.matchAll(/\sstyle="([^"]*)"/g)].map((m) => m[1]);

const scripts = blocks("script").map(hash);
const styles = [...blocks("style").map(hash), ...new Set(attrs.map(hash))];
const csp = [
  "default-src 'self'",
  `script-src 'self' ${scripts.join(" ")}`.trim(),
  `style-src 'self' https://fonts.googleapis.com ${attrs.length ? "'unsafe-hashes' " : ""}${styles.join(" ")}`.trim(),
  "font-src https://fonts.gstatic.com",
  "img-src 'self' data:",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
].join("; ");
process.stdout.write(`add_header Content-Security-Policy "${csp}" always;\n`);
