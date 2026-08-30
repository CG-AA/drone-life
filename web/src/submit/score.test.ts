import { expect, it } from "vitest";
import { myScoreText } from "./score";

it("finds the pilot's own row: points, rank among scorers, siege detail", () => {
  const rows = [
    { student_id: "s4", name: "bob", points: 35, detail: "z9 t1" },
    { student_id: "s1", name: "amy", points: 20, detail: "" },
    { student_id: "s2", name: "zed", points: 20, detail: "z3" },
  ];
  expect(myScoreText(rows, "s2")).toBe("you 20 · #3 of 3 · z3");
  expect(myScoreText(rows, "s4")).toBe("you 35 · #1 of 3 · z9 t1");
  expect(myScoreText(rows, "s1")).toBe("you 20 · #2 of 3");
});

it("is a plain zero before the first point, and off the wire", () => {
  expect(myScoreText(undefined, "s1")).toBe("you 0");
  expect(myScoreText([], "s1")).toBe("you 0");
  expect(myScoreText([{ student_id: "s9", name: "x", points: 5 }], "s1")).toBe("you 0");
});
