// B13 (web): S-04 names what the Canadian sandbox read left out. All data synthetic.
import { describe, expect, it } from "vitest";
import { skippedText } from "./routes/Quickbooks";

describe("S-04 read summary for a CAD account (B13)", () => {
  it("names the HKD documents of a multicurrency company", () => {
    expect(skippedText({ skipped_currency: [{ entity: "PurchaseOrder", currency: "HKD", count: 3 }], home_currency: "CAD", skipped_tax_inclusive: [] })).toBe(
      "3 documents in HKD skipped: this account is in CAD",
    );
  });
  it("names documents whose amounts include tax, alone or with a currency", () => {
    expect(skippedText({ skipped_currency: [], home_currency: "CAD", skipped_tax_inclusive: [{ entity: "PurchaseOrder", count: 1 }] })).toBe(
      "1 document with tax included in the amounts skipped: MatchDesk compares prices before tax",
    );
    expect(
      skippedText({
        skipped_currency: [{ entity: "Bill", currency: "USD", count: 2 }],
        home_currency: "CAD",
        skipped_tax_inclusive: [{ entity: "PurchaseOrder", count: 1 }, { entity: "Bill", count: 1 }],
      }),
    ).toBe("2 documents in USD skipped: this account is in CAD. 2 documents with tax included in the amounts skipped: MatchDesk compares prices before tax");
  });
});
