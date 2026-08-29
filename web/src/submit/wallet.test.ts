import { expect, it } from "vitest";
import { upgradesText, walletText } from "./wallet";

it("words the wallet, and stays silent for missions without one", () => {
  expect(walletText(undefined)).toBe("");
  expect(walletText({})).toBe("");
  expect(walletText({ wallet: "12" })).toBe("");
  expect(walletText({ wallet: 0 })).toBe("🪙 0 coins");
  expect(walletText({ wallet: 1 })).toBe("🪙 1 coin");
  expect(walletText({ wallet: 12.4 })).toBe("🪙 12 coins");
});

it("lists bought tiers in roman, in shop order, and nothing when stock", () => {
  expect(upgradesText(undefined)).toBe("");
  expect(upgradesText({ wallet: 3 })).toBe("");
  expect(upgradesText({ zap: 0, speed: 0, tower: 0 })).toBe("");
  expect(upgradesText({ tower: 1, zap: 2 })).toBe(" · zap II · tower I");
  expect(upgradesText({ speed: "2" })).toBe("");
});
