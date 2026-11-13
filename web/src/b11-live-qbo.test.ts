import { describe, expect, it } from "vitest";
import { skippedText } from "./routes/Quickbooks";

describe("B11-1: documents in another currency are named, never mixed silently", () => {
  it("sums skipped documents per currency and names the account's currency", () => {
    const run = {
      skipped_currency: [
        { entity: "Bill", currency: "USD", count: 2 },
        { entity: "PurchaseOrder", currency: "USD", count: 1 },
      ],
      home_currency: "CAD",
    };
    expect(skippedText(run)).toBe("3 documents in USD skipped: this account is in CAD");
    expect(skippedText({ skipped_currency: [{ entity: "Bill", currency: "EUR", count: 1 }], home_currency: "CAD" })).toBe(
      "1 document in EUR skipped: this account is in CAD",
    );
  });
  it("says nothing when nothing was skipped", () => {
    expect(skippedText({ skipped_currency: [], home_currency: "CAD" })).toBeNull();
    expect(skippedText(null)).toBeNull();
  });
});
