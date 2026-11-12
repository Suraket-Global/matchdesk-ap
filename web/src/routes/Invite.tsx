import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, send } from "../api/client";
import type { Me } from "../api/types";
import { useSession } from "../app/session";
import { usePageTitle } from "../components/ui";
import { AuthFrame } from "./Login";

/** S-02. The token is read from the fragment and sent in the POST body only. The role is the
 * one in the invitation; the invitee cannot choose it. */
export function InvitePage() {
  usePageTitle("Accept invitation");
  const token = new URLSearchParams(window.location.hash.slice(1)).get("t") ?? "";
  const [state, setState] = useState<"ready" | "pending" | "invalid" | "member">(token ? "ready" : "invalid");
  const { signedIn } = useSession();
  const navigate = useNavigate();
  async function join() {
    setState("pending");
    try {
      const me = await send<Me>("POST", "/api/v1/invitations/accept", { token });
      signedIn(me);
      history.replaceState(null, "", window.location.pathname);
      navigate("/", { replace: true });
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "member" : "invalid");
    }
  }
  return (
    <AuthFrame>
      <h1 style={{ marginBottom: 8 }}>Join your team on MatchDesk</h1>
      {(state === "ready" || state === "pending") && (
        <>
          <p>Your controller invited you. The account and your role are set by the invitation; you can see them after joining.</p>
          <button className="btn primary" onClick={join} disabled={state === "pending"} style={{ width: "100%" }}>
            {state === "pending" ? "Joining…" : "Join"}
          </button>
        </>
      )}
      {state === "invalid" && (
        <p role="alert">This invitation has expired or was revoked. Ask your controller for a new invitation.</p>
      )}
      {state === "member" && (
        <p role="alert">
          This invitation cannot be used with this address. <Link to="/login">Sign in</Link> instead.
        </p>
      )}
    </AuthFrame>
  );
}
