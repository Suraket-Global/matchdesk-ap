import type { ReactNode } from "react";
import { AlertTriangle, Check, CircleDashed, Clock, Copy, Lock, Minus, PenLine, X, type LucideIcon } from "lucide-react";

export type BadgeTone = "success" | "danger" | "warning" | "review" | "info" | "neutral";

/** A small label with a tone; colour is never the only signal, so it always carries a word. */
export function Badge({ tone = "neutral", icon, children }: { tone?: BadgeTone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={`badge ${tone}`}>
      {icon}
      {children}
    </span>
  );
}

type Tone = "matched" | "exception" | "absent" | "draft" | "approved" | "waived" | "neutral";

const ICONS: Record<string, LucideIcon> = {
  tick: Check,
  cross: X,
  absent: AlertTriangle,
  clock: Clock,
  dash: Minus,
  draft: PenLine,
  lock: Lock,
  stack: Copy,
  pending: CircleDashed,
};

export const STATUS: Record<string, { tone: Tone; icon: string; word: string }> = {
  matched: { tone: "matched", icon: "tick", word: "Matched" },
  charge_ok: { tone: "neutral", icon: "dash", word: "Charge allowed" },
  exception: { tone: "exception", icon: "cross", word: "Exception" },
  open: { tone: "exception", icon: "cross", word: "Exception" },
  receipt_absent: { tone: "absent", icon: "absent", word: "Receipt absent" },
  unverified: { tone: "absent", icon: "absent", word: "Unverified" },
  pending_approval: { tone: "draft", icon: "clock", word: "Pending approval" },
  pending: { tone: "draft", icon: "clock", word: "Pending approval" },
  waived: { tone: "waived", icon: "dash", word: "Waived" },
  resolved: { tone: "neutral", icon: "tick", word: "Resolved" },
  auto_closed: { tone: "neutral", icon: "dash", word: "Closed by a re-match" },
  needs_review: { tone: "draft", icon: "draft", word: "Needs review" },
  "needs review": { tone: "draft", icon: "draft", word: "Needs review" },
  draft: { tone: "draft", icon: "draft", word: "Draft" },
  approved: { tone: "approved", icon: "lock", word: "Approved" },
  returned: { tone: "neutral", icon: "dash", word: "Returned" },
  superseded: { tone: "waived", icon: "stack", word: "Superseded" },
  stale: { tone: "draft", icon: "clock", word: "Out of date" },
  not_evaluated: { tone: "neutral", icon: "pending", word: "Not matched yet" },
  ready: { tone: "matched", icon: "tick", word: "Ready" },
  queued: { tone: "neutral", icon: "clock", word: "Queued" },
  processing: { tone: "neutral", icon: "pending", word: "Processing" },
  failed: { tone: "exception", icon: "cross", word: "Failed" },
  "duplicate file": { tone: "absent", icon: "stack", word: "Duplicate file" },
  succeeded: { tone: "matched", icon: "tick", word: "Imported" },
  voided: { tone: "waived", icon: "dash", word: "Voided" },
  active: { tone: "matched", icon: "tick", word: "Active" },
  retired: { tone: "waived", icon: "dash", word: "Retired" },
  deactivated: { tone: "waived", icon: "dash", word: "Deactivated" },
  connected: { tone: "matched", icon: "tick", word: "Connected" },
  disconnected: { tone: "waived", icon: "dash", word: "Not connected" },
  requested: { tone: "draft", icon: "clock", word: "Requested" },
  ended: { tone: "waived", icon: "dash", word: "Ended" },
  declined: { tone: "waived", icon: "dash", word: "Declined" },
  held: { tone: "draft", icon: "clock", word: "Held for you" },
  processed: { tone: "matched", icon: "tick", word: "Accepted" },
  discarded: { tone: "waived", icon: "dash", word: "Discarded" },
  pilot: { tone: "neutral", icon: "dash", word: "Pilot" },
};

/** Status word with icon and tone from one table (DD-03). Green only for a line that passed every check. */
export function StatusPill({ status, word }: { status: string; word?: string }) {
  const c = STATUS[status] ?? { tone: "neutral" as Tone, icon: "dash", word: status.replace(/_/g, " ") };
  const I = ICONS[c.icon] ?? Minus;
  return (
    <span className={`chip ${c.tone}`}>
      <I aria-hidden="true" strokeWidth={2.5} />
      {word ?? c.word}
    </span>
  );
}

export function iconFor(name: string): LucideIcon {
  return ICONS[name] ?? Minus;
}
