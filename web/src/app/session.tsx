import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, onConnectionEvent, send, setCsrfToken } from "../api/client";
import type { Me } from "../api/types";

// The signed-in user, role and permissions. Screens never decide a permission on their own; they
// ask `can`, which mirrors schema.md 4.1 for showing controls. The server checks every request.
const PERMISSIONS: Record<string, string[]> = {
  read: ["controller", "clerk", "viewer", "support_reader"],
  read_audit: ["controller", "support_reader"],
  upload: ["controller", "clerk"],
  attest_receiving: ["controller"],
  correct_extraction: ["controller", "clerk"],
  edit_alias: ["controller", "clerk"],
  approve: ["controller"],
  resolve: ["controller", "clerk"],
  reopen: ["controller"],
  edit_tolerances: ["controller"],
  connect_qbo: ["controller"],
  start_sync: ["controller", "clerk"],
  draft_report: ["controller", "clerk"],
  approve_report: ["controller"],
  manage_users: ["controller"],
  edit_intake_settings: ["controller"],
  release_held_email: ["controller", "clerk"],
  send_weekly_summary: ["controller"],
  // B9 (schema.md 4.1 rows added with the server's table)
  assign_exception: ["controller", "clerk"],
  decide_duplicate_or_credit: ["controller"],
  record_finding_outcome: ["controller"],
  request_deletion_or_archive: ["controller"],
  // B12: delete one document (an accepted one: controller, with a reason); the account's usage.
  delete_document: ["controller", "clerk"],
  read_usage: ["controller"],
};

interface SessionValue {
  me: Me | null;
  loading: boolean;
  role: string | null;
  tenantName: string | null;
  can: (action: string) => boolean;
  signedIn: (me: Me) => void;
  signOut: () => Promise<void>;
  expired: boolean;
  offline: boolean;
  refresh: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [expired, setExpired] = useState(false);
  const [offline, setOffline] = useState(false);
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await get<Me>("/api/v1/me");
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
  const me = meQuery.data ?? null;
  useEffect(() => {
    setCsrfToken(me?.csrf_token ?? null);
    if (me) setExpired(false);
  }, [me]);
  useEffect(
    () =>
      onConnectionEvent((kind) => {
        if (kind === "expired") {
          // The server ended the session: forget who was signed in and everything read with it, so
          // sign-in does not loop on a cached user and the next person sees nothing (review W8).
          setExpired(true);
          setCsrfToken(null);
          qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
          qc.setQueryData(["me"], null);
        }
        if (kind === "offline") setOffline(true);
        if (kind === "online") setOffline(false);
      }),
    [qc],
  );
  const signedIn = useCallback(
    (fresh: Me) => {
      setCsrfToken(fresh.csrf_token);
      // Nothing from a previous session or tenant stays on screen; the "me" query keeps its observer.
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.setQueryData(["me"], fresh);
      setExpired(false);
    },
    [qc],
  );
  const signOut = useCallback(async () => {
    try {
      await send("DELETE", "/api/v1/auth/session");
    } finally {
      setCsrfToken(null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.setQueryData(["me"], null);
    }
  }, [qc]);
  const value = useMemo<SessionValue>(() => {
    const role = me?.role ?? null;
    const tenant = me?.memberships.find((m) => m.tenant_id === me.active_tenant_id);
    return {
      me,
      loading: meQuery.isLoading,
      role,
      tenantName: tenant?.tenant_name ?? me?.support?.tenant_name ?? null,
      can: (action: string) => !!role && (PERMISSIONS[action] ?? []).includes(role),
      signedIn,
      signOut,
      expired,
      offline,
      refresh: () => void meQuery.refetch(),
    };
  }, [me, meQuery, signedIn, signOut, expired, offline]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error("SessionProvider missing");
  return v;
}
