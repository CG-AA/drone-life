import { getIndentUnit } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { describe, expect, it } from "vitest";
import { pythonIndentation } from "./editor";

describe("pythonIndentation", () => {
  it("indents by four spaces, like the templates", () => {
    const state = EditorState.create({ extensions: pythonIndentation() });
    expect(getIndentUnit(state)).toBe(4);
  });
});
