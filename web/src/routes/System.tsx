import { Link, useSearchParams } from "react-router-dom";
import { PageHead, usePageTitle } from "../components/ui";
import { AuthFrame } from "./Login";

export function SignedOutPage() {
  usePageTitle("Signed out");
  const [params] = useSearchParams();
  const expired = params.get("expired") === "1";
  const next = params.get("next");
  return (
    <AuthFrame>
      <h1 style={{ marginBottom: 8 }}>You are signed out.</h1>
      {expired && <p>Your session ended after a period without activity. Your work is saved.</p>}
      <p>
        <Link className="btn primary" to={next ? `/login?next=${encodeURIComponent(next)}` : "/login"}>
          Sign in
        </Link>
      </p>
    </AuthFrame>
  );
}

export function ForbiddenPage() {
  usePageTitle("Forbidden");
  return (
    <>
      <PageHead title="Your role does not include this page" lede="Ask your controller." />
      <p>
        <Link to="/exceptions">Go to the exception queue</Link>
      </p>
    </>
  );
}

/** Identical wording for unknown routes and for records outside the user's account (S-19). */
export function NotFoundPage() {
  usePageTitle("Not found");
  return (
    <>
      <PageHead title="Not found" lede="This page or record does not exist, or you do not have access to it." />
      <p>
        <Link to="/exceptions">Go to the exception queue</Link>
      </p>
    </>
  );
}
