// Trial guidance (owner, 2026-11-19): a short guided tour of the app, step by step with Back / Next,
// that points at the real places in the navigation. It is offered once per person on a 7-day free
// trial and can be taken again from the user menu. Finished or skipped is kept on the server
// (PUT /api/v1/me/tour), never in browser storage (App-flow 4.3).
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { send } from "../api/client";
import { useSession } from "../app/session";

export interface TourStep {
  id: string;
  /** CSS selector of the element to point at; the step is centred when it is not on screen. */
  target?: string;
  title: string;
  body: ReactNode;
}

const SAMPLE_CSV = "/samples/receiving-log-sample.csv";
const SAMPLE_INVOICE = "/samples/sample-invoice.pdf";

/** The steps, in the order of the onboarding checklist. A clerk, who cannot connect QuickBooks or
 * approve, gets the shorter path. */
export function tourSteps(canConnect: boolean): TourStep[] {
  const steps: TourStep[] = [
    {
      id: "welcome",
      title: "Welcome to your 7-day free trial",
      body: (
        <>
          <p>In seven days MatchDesk checks up to 100 supplier invoices from one recent month against your purchase orders and what actually arrived.</p>
          <p>Nothing in QuickBooks changes: MatchDesk only reads. This tour takes about two minutes.</p>
        </>
      ),
    },
    {
      id: "checklist",
      target: '[data-tour="nav-onboarding"]',
      title: "Your checklist",
      body: <p>Getting started lists the four steps of the trial in order and shows which are done. Come back here whenever you are unsure what is next.</p>,
    },
    {
      id: "quickbooks",
      target: '[data-tour="nav-quickbooks"]',
      title: "1. Connect QuickBooks Online",
      body: (
        <p>
          Your controller connects once, through Intuit&apos;s own sign-in. MatchDesk reads purchase orders, bills, vendor credits, vendors and items, read-only. Then choose
          the test month on the checklist and read it from QuickBooks.
        </p>
      ),
    },
    {
      id: "receiving",
      target: '[data-tour="nav-receiving"]',
      title: "2. Load your receiving record",
      body: (
        <>
          <p>Upload what your warehouse recorded as received: a CSV or Excel export with PO number, quantity and date. You match its columns once.</p>
          <p>
            <a href={SAMPLE_CSV} download>
              Download a sample receiving file
            </a>
          </p>
        </>
      ),
    },
    {
      id: "intake",
      target: '[data-tour="nav-intake"]',
      title: "3. Upload the month's invoices",
      body: (
        <>
          <p>Drop the supplier invoices: PDFs, scans or phone photos, up to 100 in the trial. MatchDesk reads each one. Anything read from a scan, or not read with certainty, waits for you to confirm against the image.</p>
          <p>
            <a href={SAMPLE_INVOICE} download>
              See a sample invoice
            </a>
          </p>
        </>
      ),
    },
    {
      id: "exceptions",
      target: '[data-tour="nav-exceptions"]',
      title: "4. Your findings",
      body: (
        <>
          <p>Only the lines that disagree come here, each with its dollar amount and the documents behind it. A finding looks like this:</p>
          <div className="tour-example" aria-label="Example finding">
            <strong>Invoiced above received</strong>
            <span>FF-1002 line 1 · PO 4471 · HB-M8</span>
            <span>60 billed, 50 arrived: 10 × 4.20</span>
            <span className="amt">CAD 42.00</span>
          </div>
          <p className="muted small">Example from a synthetic account.</p>
        </>
      ),
    },
    {
      id: "reports",
      target: '[data-tour="nav-reports"]',
      title: "The back-test report",
      body: <p>The draft report adds up the month. During the trial you read it on screen; approving it and the PDF and CSV come with the paid pilot.</p>,
    },
    {
      id: "banner",
      target: '[data-tour="trial-banner"]',
      title: "Where you are",
      body: <p>This bar shows the day of your trial, how many invoices are used and the one next step, with a button that takes you there.</p>,
    },
    {
      id: "help",
      target: '[data-tour="user-menu"]',
      title: "Help is one click away",
      body: <p>Open this menu to take the tour again, ask for a 15-minute setup call, or write to us. We reply within one business day.</p>,
    },
  ];
  return canConnect ? steps : steps.filter((s) => s.id !== "quickbooks");
}

const TourContext = createContext<{ start: () => void } | null>(null);

/** Starts the tour from anywhere in the signed-in app (the user menu). */
export function useTour(): { start: () => void } {
  return useContext(TourContext) ?? { start: () => undefined };
}

export function TourProvider({ children }: { children: ReactNode }) {
  const { me, can } = useSession();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const offered = useRef(false);
  // Offered once, on a free-trial account, to a person who has neither finished nor skipped it.
  useEffect(() => {
    if (offered.current || !me || me.support || !me.sample || me.sample.ended || me.tour_state) return;
    offered.current = true;
    setOpen(true);
  }, [me]);
  const finish = useCallback(
    (state: "done" | "skipped") => {
      setOpen(false);
      send("PUT", "/api/v1/me/tour", { state })
        .then(() => qc.invalidateQueries({ queryKey: ["me"] }))
        .catch(() => undefined); // offered again next time, nothing else depends on it
    },
    [qc],
  );
  return (
    <TourContext.Provider value={{ start: () => setOpen(true) }}>
      {children}
      {open && <Tour steps={tourSteps(can("connect_qbo"))} onDone={() => finish("done")} onSkip={() => finish("skipped")} />}
    </TourContext.Provider>
  );
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

function visibleBox(selector?: string): Box | null {
  if (!selector) return null;
  const el = document.querySelector(selector);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 || r.height === 0 || r.bottom < 0 || r.top > window.innerHeight) return null;
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

export function Tour({ steps, onDone, onSkip }: { steps: TourStep[]; onDone: () => void; onSkip: () => void }) {
  const [i, setI] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const step = steps[i];
  const last = i === steps.length - 1;
  useLayoutEffect(() => {
    const place = () => setBox(visibleBox(step.target));
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [step]);
  useEffect(() => {
    card.current?.focus();
  }, [i]);
  useEffect(() => {
    const keys = (e: KeyboardEvent) => {
      if (e.key === "Escape") onSkip();
      else if (e.key === "ArrowRight") {
        if (last) onDone();
        else setI((n) => n + 1);
      }
      else if (e.key === "ArrowLeft") setI((n) => Math.max(0, n - 1));
    };
    document.addEventListener("keydown", keys);
    return () => document.removeEventListener("keydown", keys);
  }, [last, onDone, onSkip]);
  // Beside the highlighted element when there is room (the sidebar is on the left), else centred.
  const pad = 6;
  const cardStyle: React.CSSProperties =
    box && window.innerWidth >= 720
      ? { top: Math.min(Math.max(16, box.top - 8), window.innerHeight - 340), left: Math.min(box.left + box.width + 18, window.innerWidth - 400) }
      : {};
  return (
    <div className="tour-layer" data-testid="tour">
      {box ? (
        <div className="tour-spot" aria-hidden="true" style={{ top: box.top - pad, left: box.left - pad, width: box.width + 2 * pad, height: box.height + 2 * pad }} />
      ) : (
        <div className="tour-dim" aria-hidden="true" />
      )}
      <div
        ref={card}
        className={`tour-card ${box && window.innerWidth >= 720 ? "anchored" : "centred"}`}
        style={cardStyle}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        tabIndex={-1}
      >
        <p className="tour-count">
          Step {i + 1} of {steps.length}
        </p>
        <h2 id="tour-title">{step.title}</h2>
        <div className="tour-body">{step.body}</div>
        <div className="tour-actions">
          <button className="btn ghost small" onClick={onSkip}>
            Skip tour
          </button>
          <span className="spacer" />
          {i > 0 && (
            <button className="btn small" onClick={() => setI(i - 1)}>
              Back
            </button>
          )}
          <button className="btn primary small" onClick={() => (last ? onDone() : setI(i + 1))}>
            {last ? "Finish" : i === 0 ? "Start the tour" : "Next"}
          </button>
        </div>
        <div className="tour-dots" aria-hidden="true">
          {steps.map((s, n) => (
            <span key={s.id} className={n === i ? "on" : ""} />
          ))}
        </div>
      </div>
    </div>
  );
}

/** A small "?" that opens a short explanation in place (trial guidance, 2026-11-19). */
export function HelpTip({ label, children, align = "left" }: { label: string; children: ReactNode; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <span className={`help-tip ${align}`} ref={wrap}>
      <button type="button" className="help-tip-btn" aria-expanded={open} aria-label={`Help: ${label}`} onClick={() => setOpen((o) => !o)}>
        ?
      </button>
      {open && (
        <span className="help-tip-pop" role="note">
          {children}
        </span>
      )}
    </span>
  );
}

export const SAMPLE_FILES = { receiving: SAMPLE_CSV, invoice: SAMPLE_INVOICE };
