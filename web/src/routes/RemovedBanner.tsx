import type { InvoiceDetail } from "../api/types";
import { Banner } from "../components/ui";
import { when } from "../lib/format";

/** B12: a deleted document is history only. Shown on S-07 and S-09. */
export function RemovedBanner({ removed }: { removed: NonNullable<InvoiceDetail["removed"]> }) {
  return (
    <Banner tone="draft" role="status">
      <p>
        <strong>Deleted {when(removed.removed_at)}</strong>
        {removed.removed_by_name ? ` by ${removed.removed_by_name}` : ""}
        {removed.reason ? `: ${removed.reason}` : "."} It is out of matching, the queue and new reports, and is kept here as history.
      </p>
    </Banner>
  );
}
