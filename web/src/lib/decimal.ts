// Money and quantities arrive from the API as decimal strings. The web app never turns them into
// binary floats (CLAUDE.md "No floats in money or quantity arithmetic"): sums use integer cents
// in BigInt, display only inserts separators into the string.

/** "1234.5" -> 123450n cents; more than two decimals are rounded half up. null for empty input. */
export function toCents(value: string | null | undefined): bigint | null {
  if (value === null || value === undefined) return null;
  const s = String(value).trim();
  const m = /^(-)?(\d*)(?:\.(\d*))?$/.exec(s);
  if (!m || (m[2] === "" && (m[3] ?? "") === "")) return null;
  const neg = m[1] === "-";
  const whole = BigInt(m[2] || "0");
  const frac = (m[3] ?? "").padEnd(3, "0");
  let cents = whole * 100n + BigInt(frac.slice(0, 2));
  if (Number(frac[2]) >= 5) cents += 1n;
  return neg ? -cents : cents;
}

export function sumCents(values: Array<string | null | undefined>): bigint {
  return values.reduce<bigint>((acc, v) => acc + (toCents(v) ?? 0n), 0n);
}

/** 123450n -> "1,234.50" (with "-" for negatives). */
export function formatCents(cents: bigint): string {
  const neg = cents < 0n;
  const abs = neg ? -cents : cents;
  const whole = (abs / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = (abs % 100n).toString().padStart(2, "0");
  return `${neg ? "-" : ""}${whole}.${frac}`;
}

/** A money string for display: "1234.5" -> "1,234.50"; empty for null. */
export function money(value: string | null | undefined): string {
  const c = toCents(value);
  return c === null ? "" : formatCents(c);
}

/** "CAD 1,234.50". */
export function cad(value: string | null | undefined): string {
  const m = money(value);
  return m ? `CAD ${m}` : "";
}

/** "CAD 1,234.50" from integer cents. */
export function cadCents(cents: bigint): string {
  return `CAD ${formatCents(cents)}`;
}

/** A quantity string without trailing zeros: "60.0000" -> "60", "12.500" -> "12.5". */
export function qty(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const s = String(value);
  if (!s.includes(".")) return s;
  return s.replace(/0+$/, "").replace(/\.$/, "");
}

/** Compare two decimal strings exactly. */
export function compareDecimal(a: string, b: string): number {
  const [ai, af = ""] = a.replace("-", "").split(".");
  const [bi, bf = ""] = b.replace("-", "").split(".");
  const len = Math.max(af.length, bf.length);
  const an = BigInt(ai + af.padEnd(len, "0")) * (a.startsWith("-") ? -1n : 1n);
  const bn = BigInt(bi + bf.padEnd(len, "0")) * (b.startsWith("-") ? -1n : 1n);
  return an === bn ? 0 : an < bn ? -1 : 1;
}

/** Whether a user-typed value is a non-negative decimal number. */
export function isDecimal(value: string): boolean {
  return /^\d+(\.\d+)?$/.test(value.trim());
}

/** Multiply two decimal strings exactly; result rounded half up to `places`. For worked examples. */
export function multiply(a: string, b: string, places = 2): string {
  const split = (v: string) => {
    const [i, f = ""] = v.trim().split(".");
    return { n: BigInt((i || "0") + f), d: f.length };
  };
  const x = split(a);
  const y = split(b);
  return scale(x.n * y.n, x.d + y.d, places);
}

/** Divide a by b exactly; result rounded half up to `places`. */
export function divide(a: string, b: string, places = 2): string {
  const split = (v: string) => {
    const [i, f = ""] = v.trim().split(".");
    return { n: BigInt((i || "0") + f), d: f.length };
  };
  const x = split(a);
  const y = split(b);
  if (y.n === 0n) return "";
  // a/b = (x.n / 10^x.d) / (y.n / 10^y.d) = x.n * 10^(y.d) / (y.n * 10^(x.d))
  const extra = places + 1;
  const num = x.n * 10n ** BigInt(y.d + extra);
  const den = y.n * 10n ** BigInt(x.d);
  return scale(num / den, extra, places);
}

function scale(n: bigint, decimals: number, places: number): string {
  let v = n;
  let d = decimals;
  if (d > places) {
    const f = 10n ** BigInt(d - places);
    v = (v + f / 2n) / f;
    d = places;
  }
  const s = v.toString().padStart(d + 1, "0");
  const out = d === 0 ? s : `${s.slice(0, -d)}.${s.slice(-d)}`;
  return out;
}

/** A unit price: trailing zeros beyond the cents are dropped, the cents are kept ("4.20", "0.075"). */
export function price(value: string | null | undefined): string {
  const s = qty(value);
  if (!s) return s;
  const [i, f = ""] = s.split(".");
  return `${i}.${f.padEnd(2, "0")}`;
}

/** a - b exactly, as a decimal string without trailing zeros ("100" - "60" -> "40"). For the
 * difference column of the match view; the stored result stays the authority. */
export function subtract(a: string, b: string): string {
  const parse = (v: string) => {
    const neg = v.trim().startsWith("-");
    const [i, f = ""] = v.trim().replace("-", "").split(".");
    return { n: BigInt((i || "0") + f) * (neg ? -1n : 1n), d: f.length };
  };
  const x = parse(a);
  const y = parse(b);
  const d = Math.max(x.d, y.d);
  const n = x.n * 10n ** BigInt(d - x.d) - y.n * 10n ** BigInt(d - y.d);
  const neg = n < 0n;
  const out = scale(neg ? -n : n, d, d);
  return (neg ? "-" : "") + qty(out);
}
