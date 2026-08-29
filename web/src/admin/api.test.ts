import { describe, expect, it } from "vitest";
import { tokenProblem } from "./api";

describe("tokenProblem", () => {
  it("accepts a real token", () => {
    expect(tokenProblem("f7ADUaBMOMLiYLSxn1arcQgSwaumcTIB")).toBeNull();
    expect(tokenProblem("abc+/=123")).toBeNull();
  });
  it("names a paste of password-mask bullets", () => {
    expect(tokenProblem("●●●●●●●●●●")).toMatch(/masked dots/);
    expect(tokenProblem("••••••••")).toMatch(/masked dots/);
  });
  it("rejects anything fetch() could not put in a header", () => {
    expect(tokenProblem("")).toMatch(/paste/);
    expect(tokenProblem("with space")).toMatch(/ASCII/);
    expect(tokenProblem("tökén")).toMatch(/ASCII/);
  });
});
