import { Link, useSearchParams } from "react-router-dom";
import { SearchX, ShieldAlert } from "lucide-react";
import { Empty, PageHead, usePageTitle } from "../components/ui";
import { AuthFrame } from "./Login";

export function SignedOutPage() {
  usePageTitle("Signed out");
  const [params] = useSearchParams();
  const expired = params.get("expired") === "1";
  const next = params.get("next");
  return (
    <AuthFrame>
      <h1>You are signed out.</h1>
      {expired && <p>Your session ended after a period without activity. Your work is saved.</p>}
      <p style={{ marginTop: 16 }}>
        <Link className="btn primary block" to={next ? `/login?next=${encodeURIComponent(next)}` : "/login"}>
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
      <PageHead title="Your role does not include this page" lede="Ask your controller if you need it." />
      <div className="panel">
        <Empty title="No access with your role" icon={<ShieldAlert size={22} />} action={<Link className="btn primary" to="/exceptions">Go to the exception queue</Link>} />
      </div>
    </>
  );
}

/** Identical wording for unknown routes and for records outside the user's account (S-19). */
export function NotFoundPage() {
  usePageTitle("Not found");
  return (
    <>
      <PageHead title="Not found" lede="This page or record does not exist, or you do not have access to it." />
      <div className="panel">
        <Empty title="Nothing at this address" icon={<SearchX size={22} />} action={<Link className="btn primary" to="/exceptions">Go to the exception queue</Link>} />
      </div>
    </>
  );
}
