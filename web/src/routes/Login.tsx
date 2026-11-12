import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, send } from "../api/client";
import type { Me } from "../api/types";
import { useSession } from "../app/session";
import { usePageTitle } from "../components/ui";

const MAILPIT = "http://127.0.0.1:8025";
// Shown only in a development build (Vite's `DEV` flag); a production build drops it.
const SHOW_DEV_MAIL_NOTE = import.meta.env.DEV;

export function AuthFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-page">
      <main className="auth-card" id="main">
        <div className="brand">
          <img className="brand-mark" src="/favicon.svg" alt="" />
          MatchDesk
        </div>
        {children}
      </main>
    </div>
  );
}

function DevMailNote() {
  if (!SHOW_DEV_MAIL_NOTE) return null;
  return (
    <p className="dev-note">
      Local development: open Mailpit to get your link,{" "}
      <a href={MAILPIT} target="_blank" rel="noreferrer">
        {MAILPIT}
      </a>
      .
    </p>
  );
}

export function EmailForm({ intro }: { intro?: string }) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "pending" | "sent" | "limited" | "error">("idle");
  const [invalid, setInvalid] = useState<string | null>(null);
  const [params] = useSearchParams();
  const { refresh } = useSession();
  useEffect(() => {
    // The link usually opens in a new tab. This tab watches for the session and then returns to
    // the page that was asked for (deep link restored, nothing kept in browser storage).
    if (state !== "sent") return;
    const t = window.setInterval(refresh, 3000);
    return () => window.clearInterval(t);
  }, [state, refresh]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      setInvalid("Enter your work email address, for example dana@example.test.");
      return;
    }
    setInvalid(null);
    setState("pending");
    try {
      await send("POST", "/api/v1/auth/login-links", { email: email.trim() });
      setState("sent");
    } catch (err) {
      setState(err instanceof ApiError && err.status === 429 ? "limited" : "error");
    }
  }
  const next = params.get("next");
  return (
    <form onSubmit={submit} noValidate>
      {intro && <p>{intro}</p>}
      <div className="field">
        <label htmlFor="email">Work email</label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={!!invalid}
          aria-describedby={invalid ? "email-err" : undefined}
          disabled={state === "pending"}
          style={{ width: "100%" }}
        />
        {invalid && (
          <span className="error" id="email-err">
            {invalid}
          </span>
        )}
      </div>
      <button className="btn primary" type="submit" disabled={state === "pending"} style={{ width: "100%" }}>
        {state === "pending" ? "Sending…" : "Email me a sign-in link"}
      </button>
      <div role="status" aria-live="polite" style={{ marginTop: 12 }}>
        {state === "sent" && (
          <p>If that address has access, a link is on its way. It works once, in this browser, and expires in 10 minutes.</p>
        )}
        {state === "limited" && <p className="error-text">Too many requests. Try again in a few minutes.</p>}
        {state === "error" && <p className="error-text">The link could not be sent. Try again.</p>}
      </div>
      {next && <p className="muted small">After you sign in, you return to the page you asked for.</p>}
      <DevMailNote />
    </form>
  );
}

function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginPage() {
  usePageTitle("Sign in");
  const { me } = useSession();
  const [params] = useSearchParams();
  if (me) return <Navigate to={safeNext(params.get("next"))} replace />;
  return (
    <AuthFrame>
      <h1 style={{ marginBottom: 8 }}>Sign in</h1>
      <EmailForm intro="We email you a link. There is no password." />
    </AuthFrame>
  );
}

/** S-01 /login/verify: the token is in the fragment, never sent in a URL; opening uses nothing up. */
export function VerifyPage() {
  usePageTitle("Sign in");
  const token = new URLSearchParams(window.location.hash.slice(1)).get("t") ?? "";
  const [state, setState] = useState<"ready" | "pending" | "expired" | "other" | "totp" | "limited">(
    token ? "ready" : "expired",
  );
  const [code, setCode] = useState("");
  const { signedIn } = useSession();
  const navigate = useNavigate();
  async function signIn() {
    setState("pending");
    try {
      const me = await send<Me>("POST", "/api/v1/auth/sessions", { token, totp_code: code || undefined });
      signedIn(me);
      history.replaceState(null, "", window.location.pathname);
      const next = new URLSearchParams(window.location.search).get("next");
      navigate(safeNext(next), { replace: true });
    } catch (err) {
      const s = err instanceof ApiError ? err.status : 0;
      setState(s === 409 ? "other" : s === 401 ? "totp" : s === 429 ? "limited" : "expired");
    }
  }
  return (
    <AuthFrame>
      <h1 style={{ marginBottom: 8 }}>Sign in</h1>
      {(state === "ready" || state === "pending" || state === "totp") && (
        <>
          <p>Sign in to MatchDesk in this browser?</p>
          {state === "totp" && (
            <div className="field">
              <label htmlFor="totp">One-time code from your authenticator app</label>
              <input id="totp" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            </div>
          )}
          <button className="btn primary" onClick={signIn} disabled={state === "pending"} style={{ width: "100%" }}>
            {state === "pending" ? "Signing in…" : "Sign in"}
          </button>
        </>
      )}
      {state === "expired" && (
        <>
          <p role="alert">This link has expired or was already used.</p>
          <EmailForm />
        </>
      )}
      {state === "other" && (
        <>
          <p role="alert">Open this link in the browser where you asked for it, or send a new link to this one.</p>
          <EmailForm />
        </>
      )}
      {state === "limited" && <p role="alert">Too many requests. Try again in a few minutes.</p>}
      <p className="small muted" style={{ marginTop: 16 }}>
        <Link to="/login">Back to sign in</Link>
      </p>
    </AuthFrame>
  );
}
