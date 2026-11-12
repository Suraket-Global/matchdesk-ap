// The one HTTP client. Tenant comes from the session cookie (httponly), never from the app.
// The anti-forgery token is kept in memory only (no browser storage) and read again from /me
// after a reload. Every mutating request carries an idempotency key; a timed-out write is retried
// once with the same key, so a retry never doubles an effect (App-flow.md section 5).

export class ApiError extends Error {
  status: number;
  title: string;
  current?: unknown;
  correlationId?: string;
  constructor(status: number, title: string, current?: unknown, correlationId?: string) {
    super(title);
    this.status = status;
    this.title = title;
    this.current = current;
    this.correlationId = correlationId;
  }
}

let csrfToken: string | null = null;
let lastContact = Date.now();

/** When the server last saw this browser; the 60-minute idle limit runs from here. */
export function lastServerContact(): number {
  return lastContact;
}

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function newKey(): string {
  return crypto.randomUUID();
}

type Listener = (kind: "expired" | "offline" | "online") => void;
const listeners = new Set<Listener>();
export function onConnectionEvent(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function emit(kind: "expired" | "offline" | "online"): void {
  listeners.forEach((fn) => fn(kind));
}

const PUBLIC = ["/api/v1/auth/login-links", "/api/v1/auth/sessions", "/api/v1/invitations/accept", "/api/v1/me"];

export interface SendOptions {
  ifMatch?: number | string;
  idempotencyKey?: string;
  timeoutMs?: number;
}

async function request(
  method: string,
  path: string,
  body?: BodyInit | null,
  headers: Record<string, string> = {},
  timeoutMs = 30_000,
): Promise<Response> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(path, {
      method,
      body,
      headers,
      credentials: "same-origin",
      signal: ctrl.signal,
    });
    emit("online");
    if (res.status !== 401) lastContact = Date.now();
    return res;
  } catch (err) {
    emit("offline");
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

async function problem(res: Response): Promise<ApiError> {
  let title = res.statusText || "The request failed";
  let current: unknown;
  let corr: string | undefined;
  try {
    const j = await res.json();
    title = j.title || j.detail || title;
    current = j.current;
    corr = j.correlation_id;
  } catch {
    /* not JSON */
  }
  if (res.status === 401 && !PUBLIC.some((p) => res.url.endsWith(p))) emit("expired");
  return new ApiError(res.status, title, current, corr);
}

export async function get<T>(path: string): Promise<T> {
  const res = await request("GET", path, null, { Accept: "application/json" });
  if (!res.ok) throw await problem(res);
  return (await res.json()) as T;
}

export async function send<T>(method: string, path: string, body?: unknown, opts: SendOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  if (opts.ifMatch !== undefined) headers["If-Match"] = String(opts.ifMatch);
  headers["Idempotency-Key"] = opts.idempotencyKey ?? newKey();
  const payload = body === undefined ? null : JSON.stringify(body);
  let res: Response;
  try {
    res = await request(method, path, payload, headers, opts.timeoutMs);
  } catch {
    // One retry with the same key: the server applies the effect at most once.
    res = await request(method, path, payload, headers, opts.timeoutMs);
  }
  if (!res.ok) throw await problem(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function upload<T>(path: string, form: FormData, idempotencyKey?: string): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  headers["Idempotency-Key"] = idempotencyKey ?? newKey();
  const res = await request("POST", path, form, headers, 120_000);
  if (!res.ok) throw await problem(res);
  return (await res.json()) as T;
}

/** A file download through the API (report exports, audit CSV): fetched, then saved by the browser. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const res = await request("GET", path, null, {}, 120_000);
  if (!res.ok) throw await problem(res);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Bytes of a stored document, for PDF.js (never a storage link: TRD 8.7). */
export async function documentBytes(documentId: string): Promise<ArrayBuffer> {
  const res = await request("GET", `/api/v1/documents/${documentId}/content`, null, {}, 60_000);
  if (!res.ok) throw await problem(res);
  return res.arrayBuffer();
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "Your role does not allow this. Ask your controller.";
    if (err.status === 404) return "Not found. It may have been removed, or it belongs to another account.";
    if (err.status === 429) return "Too many requests. Try again in a few minutes.";
    if (err.status >= 500) return "The server could not complete this. Try again; if it keeps failing, note the time and tell support.";
    return err.title.charAt(0).toUpperCase() + err.title.slice(1);
  }
  return "Connection lost. Check your network and try again.";
}
