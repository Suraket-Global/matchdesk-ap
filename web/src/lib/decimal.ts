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
  const x = split(a);
  const y = split(b);
  if (!x || !y) return x ? 1 : y ? -1 : 0; // not a number sorts first; never throws
  const len = Math.max(x.d, y.d);
  const an = x.n * 10n ** BigInt(len - x.d);
  const bn = y.n * 10n ** BigInt(len - y.d);
  return an === bn ? 0 : an < bn ? -1 : 1;
}

/** Whether a user-typed value is a non-negative decimal number. */
export function isDecimal(value: string): boolean {
  return /^\d+(\.\d+)?$/.test(value.trim());
}

/** A decimal string as an exact integer and its number of decimals; null for anything else, so a
 * helper below never throws on what a person typed (B10, outside QA item 3). */
function split(v: string): { n: bigint; d: number } | null {
  const m = /^(-)?(\d*)(?:\.(\d*))?$/.exec(String(v).trim());
  if (!m || (m[2] === "" && (m[3] ?? "") === "")) return null;
  const f = m[3] ?? "";
  const n = BigInt((m[2] || "0") + f);
  return { n: m[1] ? -n : n, d: f.length };
}

/** Multiply two decimal strings exactly; result rounded half up to `places`. For worked examples.
 * Empty for input that is not a plain decimal. */
export function multiply(a: string, b: string, places = 2): string {
  const x = split(a);
  const y = split(b);
  if (!x || !y) return "";
  return scale(x.n * y.n, x.d + y.d, places);
}

/** Divide a by b exactly; result rounded half up to `places`. */
export function divide(a: string, b: string, places = 2): string {
  const x = split(a);
  const y = split(b);
  if (!x || !y || y.n === 0n) return "";
  // a/b = (x.n / 10^x.d) / (y.n / 10^y.d) = x.n * 10^(y.d) / (y.n * 10^(x.d))
  const extra = places + 1;
  const num = x.n * 10n ** BigInt(y.d + extra);
  const den = y.n * 10n ** BigInt(x.d);
  return scale(num / den, extra, places);
}

/** Round n / 10^decimals to `places` decimals, half up: a half is rounded away from zero, as
 * Python's ROUND_HALF_UP does (TRD 8.4), so -1 x 1.235 = -1.24, not -1.23 (B10, item 4). */
function scale(n: bigint, decimals: number, places: number): string {
  const neg = n < 0n;
  let v = neg ? -n : n;
  let d = decimals;
  if (d > places) {
    const f = 10n ** BigInt(d - places);
    v = (v + f / 2n) / f;
    d = places;
  }
  const s = v.toString().padStart(d + 1, "0");
  const out = d === 0 ? s : `${s.slice(0, -d)}.${s.slice(-d)}`;
  return neg && v !== 0n ? `-${out}` : out;
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
  const x = split(a);
  const y = split(b);
  if (!x || !y) return "";
  const d = Math.max(x.d, y.d);
  const n = x.n * 10n ** BigInt(d - x.d) - y.n * 10n ** BigInt(d - y.d);
  const neg = n < 0n;
  const out = scale(neg ? -n : n, d, d);
  return (neg ? "-" : "") + qty(out);
}

// ------------------------------------------------------------------ typed input (B10, item 3)

export type ParsedNumber = { ok: true; value: string } | { ok: false; error: string };

export interface NumberRules {
  /** Decimal places the stored column keeps: money 2, quantity 4, unit price 6. */
  places: number;
  /** Digits before the decimal point the column holds (NUMERIC(14, places)). */
  whole: number;
  negative?: boolean;
}

export const MONEY_INPUT: NumberRules = { places: 2, whole: 12, negative: true };
export const QTY_INPUT: NumberRules = { places: 4, whole: 10, negative: true };
export const PRICE_INPUT: NumberRules = { places: 6, whole: 8, negative: true };
export const AMOUNT_INPUT: NumberRules = { places: 2, whole: 12 };
export const FACTOR_INPUT: NumberRules = { places: 6, whole: 8 };
export const PERCENT_INPUT: NumberRules = { places: 2, whole: 3 };

/** What a person typed or pasted as a plain decimal string ("1,000.50" -> "1000.50"), or a reason
 * to show next to the field. Thousands separators are accepted where they are unambiguous: commas
 * or spaces between groups of three digits before a dot. "1.000,5" and "1,5" are refused (a comma
 * is never a decimal mark here), as are letters, a lone minus sign and numbers too large for the
 * column. Empty input is { ok: true, value: "" }; the caller decides whether the field is required.
 * Never throws. */
export function parseNumberInput(raw: string | null | undefined, rules: NumberRules = MONEY_INPUT): ParsedNumber {
  let s = String(raw ?? "").replace(/[\u00a0\u202f\u2009]/g, " ").trim();
  if (s === "") return { ok: true, value: "" };
  s = s.replace(/^(cad|\$)\s*/i, "");
  let sign = "";
  if (/^[-\u2212]/.test(s)) {
    sign = "-";
    s = s.slice(1).trim();
  }
  if (s === "") return { ok: false, error: "Type a number after the minus sign, for example -12.50." };
  if (s.includes(" ")) {
    if (!/^\d{1,3}( \d{3})+(\.\d+)?$/.test(s)) return { ok: false, error: "Spaces go only between groups of three digits, as in 1 000.50." };
    s = s.replace(/ /g, "");
  }
  if (s.includes(",")) {
    if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) s = s.replace(/,/g, "");
    else if (/^\d{1,3}(\.\d{3})*,\d+$/.test(s)) return { ok: false, error: "Use a dot for decimals: write 1000.50, not 1.000,50." };
    else return { ok: false, error: "Commas go only between groups of three digits, as in 1,000.50." };
  }
  if (!/^\d*\.?\d*$/.test(s) || s === ".") return { ok: false, error: "Use digits, with a dot for decimals, for example 1000.50." };
  const [w, f = ""] = s.split(".");
  if (f.length > rules.places) return { ok: false, error: rules.places === 0 ? "Whole numbers only." : `At most ${rules.places} decimal places.` };
  const whole = (w ?? "").replace(/^0+(?=\d)/, "") || "0";
  if (whole.length > rules.whole) return { ok: false, error: `This number is too large (at most ${rules.whole} digits before the decimal point).` };
  const zero = /^0*$/.test(whole + f);
  if (sign && !zero && !rules.negative) return { ok: false, error: "This field takes no negative number." };
  return { ok: true, value: `${sign && !zero ? "-" : ""}${whole}${f ? `.${f}` : ""}` };
}

/** The plain value of a typed number, or "" when it cannot be read (for live examples and sums). */
export function plainNumber(raw: string | null | undefined, rules: NumberRules = MONEY_INPUT): string {
  const p = parseNumberInput(raw, rules);
  return p.ok ? p.value : "";
}

/** The reason a typed number cannot be used, or null. */
export function numberError(raw: string | null | undefined, rules: NumberRules = MONEY_INPUT): string | null {
  const p = parseNumberInput(raw, rules);
  return p.ok ? null : p.error;
}
