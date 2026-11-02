import { describe, expect, it } from "vitest";
import { decimalSubtract, formatDate, formatMoney, formatQuantity, groupDigits, isOverdue } from "./format";

describe("money formatting", () => {
  it("groups digits without changing them", () => {
    expect(groupDigits("6890.00")).toBe("6,890.00");
    expect(groupDigits("1234567.891")).toBe("1,234,567.891");
    expect(groupDigits("-15000")).toBe("-15,000");
    expect(groupDigits("0.10")).toBe("0.10");
  });

  it("keeps precision a float would lose", () => {
    expect(formatMoney("90071992547409930.01", "USD")).toBe("USD 90,071,992,547,409,930.01");
  });

  it("always shows the currency and an em dash when missing", () => {
    expect(formatMoney("4125.00", "EUR")).toBe("EUR 4,125.00");
    expect(formatMoney(null, "USD")).toBe("—");
  });

  it("subtracts decimals exactly", () => {
    expect(decimalSubtract("22562.80", "22512.80")).toBe("50.00");
    expect(decimalSubtract("0.1", "0.3")).toBe("-0.2");
    expect(decimalSubtract("10", "0.05")).toBe("9.95");
  });

  it("formats quantities and dates", () => {
    expect(formatQuantity("20.00")).toBe("20");
    expect(formatQuantity(15)).toBe("15");
    expect(formatDate("2026-02-01")).toBe("Feb 1, 2026");
    expect(isOverdue("2026-02-01", "2026-11-01")).toBe(true);
    expect(isOverdue("2026-02-01", "2026-01-20")).toBe(false);
  });
});
