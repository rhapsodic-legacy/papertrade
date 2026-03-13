import { formatCurrency, formatPrice, formatNumber, formatDate, pnlColor } from "@/lib/utils";

describe("formatCurrency", () => {
  it("formats positive numbers", () => {
    expect(formatCurrency(100000)).toBe("$100,000.00");
  });

  it("formats small numbers with cents", () => {
    expect(formatCurrency(42.5)).toBe("$42.50");
  });

  it("formats zero", () => {
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("formats negative numbers", () => {
    expect(formatCurrency(-1500.75)).toBe("-$1,500.75");
  });
});

describe("formatPrice", () => {
  it("shows 4 decimals for stock-range prices", () => {
    expect(formatPrice(175.5)).toBe("$175.5000");
  });

  it("shows 6 decimals for sub-dollar prices", () => {
    expect(formatPrice(0.01234)).toBe("$0.012340");
  });

  it("shows 4 decimals for crypto above $1", () => {
    expect(formatPrice(65000.1234)).toBe("$65,000.1234");
  });
});

describe("formatNumber", () => {
  it("formats with default 2 decimals", () => {
    expect(formatNumber(1234.5678)).toBe("1,234.57");
  });

  it("formats with custom decimals", () => {
    expect(formatNumber(1234.5, 0)).toBe("1,235");
  });
});

describe("pnlColor", () => {
  it("returns green for positive", () => {
    expect(pnlColor(100)).toBe("text-green-500");
  });

  it("returns red for negative", () => {
    expect(pnlColor(-50)).toBe("text-red-500");
  });

  it("returns gray for zero", () => {
    expect(pnlColor(0)).toBe("text-gray-400");
  });
});

describe("formatDate", () => {
  it("formats ISO date string", () => {
    const result = formatDate("2026-03-11T14:30:00Z");
    expect(result).toContain("Mar");
    expect(result).toContain("11");
    expect(result).toContain("2026");
  });
});
