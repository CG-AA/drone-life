import { expect, it } from "vitest";
import { walletText } from "./wallet";

it("words the wallet, and stays silent for missions without one", () => {
  expect(walletText(undefined)).toBe("");
  expect(walletText({})).toBe("");
  expect(walletText({ wallet: "12" })).toBe("");
  expect(walletText({ wallet: 0 })).toBe("🪙 0 coins");
  expect(walletText({ wallet: 1 })).toBe("🪙 1 coin");
  expect(walletText({ wallet: 12.4 })).toBe("🪙 12 coins");
});
