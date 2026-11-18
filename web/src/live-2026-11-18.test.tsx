// Fixes from the live QuickBooks test of 2026-11-18.
import { describe, expect, it } from "vitest";
import { monthFromAddress } from "./app/period";

describe("top-bar period from the address", () => {
  it("opens on the month a link or reload carries", () => {
    expect(monthFromAddress("?period=2026-11")).toBe("2026-11");
    expect(monthFromAddress("?month=2026-09&x=1")).toBe("2026-09");
  });
  it("ignores anything that is not a month", () => {
    expect(monthFromAddress("")).toBeNull();
    expect(monthFromAddress("?period=2026-13")).toBeNull();
    expect(monthFromAddress("?period=november")).toBeNull();
  });
});
