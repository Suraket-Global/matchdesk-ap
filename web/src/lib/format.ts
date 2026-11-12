// One display format everywhere: "3 Oct 2026", "3 Oct, 14:05" (B6 review minor).
const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
const DATETIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

/** "2026-10-03" -> "3 Oct 2026" without shifting the day by time zone. */
export function day(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map((p) => Number(p));
  return DATE.format(new Date(y, m - 1, d));
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  return DATETIME.format(new Date(iso));
}

export function time(iso: string | null | undefined): string {
  if (!iso) return "";
  return TIME.format(new Date(iso));
}

/** Age in whole days, for the queue. */
export function ageDays(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const ms = now.getTime() - new Date(iso).getTime();
  return Math.max(0, Math.floor(ms / 86_400_000));
}

export function ageText(iso: string | null | undefined): string {
  const d = ageDays(iso);
  if (d === null) return "";
  return d === 0 ? "today" : d === 1 ? "1 day" : `${d} days`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-CA")} ${n === 1 ? one : many}`;
}

/** The month before `now` as yyyy-mm, the default test month. */
export function lastMonth(now: Date = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function monthRange(ym: string): { start: string; end: string } {
  const [y, m] = ym.split("-").map((p) => Number(p));
  const last = new Date(y, m, 0).getDate();
  return { start: `${ym}-01`, end: `${ym}-${String(last).padStart(2, "0")}` };
}

export function monthName(ym: string): string {
  const [y, m] = ym.split("-").map((p) => Number(p));
  return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(new Date(y, m - 1, 1));
}

/** A same-site path to go back to, or the fallback. Refuses absolute URLs, `//host`, backslashes and
 * `javascript:` (used for `?next=` after sign-in and `?from=` on the match view; review W1). */
export function safePath(value: string | null | undefined, fallback = "/"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return fallback;
  // eslint-disable-next-line no-control-regex -- refusing control characters is the point
  if (/[\u0000-\u001f\\]/.test(value)) return fallback;
  return value;
}
