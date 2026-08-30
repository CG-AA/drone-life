import { expect, it } from "vitest";
import { sourceLabel } from "./building";

it("labels a pile by its stock: infinite, counted, or spent", () => {
  expect(sourceLabel({ material: "steel", remaining: null })).toBe("STEEL");
  expect(sourceLabel({ material: "clay" })).toBe("CLAY");
  expect(sourceLabel({ material: "steel", remaining: 12 })).toBe("STEEL · 12");
  expect(sourceLabel({ material: "steel", remaining: 0 })).toBe("STEEL · EMPTY");
});
