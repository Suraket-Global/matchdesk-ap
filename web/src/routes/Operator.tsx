import { Empty, PageHead, usePageTitle } from "../components/ui";

/** S-18: the operator API (tenants, pilot records, usage, support sessions) is not built yet. */
export function OperatorPage() {
  usePageTitle("Operator console");
  return (
    <>
      <PageHead title="Operator console" lede="Set up pilot accounts and record what was agreed and paid." />
      <div className="panel">
        <Empty title="Not built yet">
          <p>
            Creating tenants, pilot records, billable-unit counts and support sessions need operator endpoints that are a later milestone. Until then the
            demo tenant is created by make seed-demo, and no operator can see any account's data.
          </p>
        </Empty>
      </div>
    </>
  );
}
