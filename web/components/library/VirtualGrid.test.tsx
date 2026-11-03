// TM11-142. Column and row maths for the library's cover grid.
import { describe, expect, it } from "vitest";
import { gridMetrics, type GridShape } from "./VirtualGrid";

const SHAPE: GridShape = { minCardWidth: 168, gap: 20, rowGap: 28, captionHeight: 60, minColumns: 2 };

describe("gridMetrics", () => {
  it("fits as many columns as the width allows", () => {
    // (1344 + 20) / (168 + 20) = 7.25 → 7 columns
    const m = gridMetrics(1344, SHAPE);
    expect(m.columns).toBe(7);
    expect(m.cardWidth).toBeCloseTo((1344 - 20 * 6) / 7);
  });

  it("keeps at least two columns on a phone", () => {
    expect(gridMetrics(343, SHAPE).columns).toBe(2);
  });

  it("makes a row the 2:3 cover plus the caption and the row gap", () => {
    const m = gridMetrics(1344, SHAPE);
    expect(m.rowHeight).toBe(Math.round(m.cardWidth * 1.5 + 60 + 28));
  });

  it("falls back to a fixed height before the list is measured", () => {
    expect(gridMetrics(0, SHAPE)).toEqual({ columns: 2, cardWidth: 0, rowHeight: 320 });
  });
});
