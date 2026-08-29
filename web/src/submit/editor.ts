/** CodeMirror 6 python editor. */

import { indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { indentUnit } from "@codemirror/language";
import { lintGutter, setDiagnostics } from "@codemirror/lint";
import { oneDark } from "@codemirror/theme-one-dark";
import { keymap } from "@codemirror/view";
import { EditorView, basicSetup } from "codemirror";
import { diagnosticRange } from "./position";

const DRAFT_KEY = "dl_draft";

/** Python indentation the way the templates are written: four spaces, and
 * Tab indents instead of moving focus to the next button (CodeMirror leaves
 * Tab unbound by default; Escape then Tab still walks out of the editor). */
export function pythonIndentation() {
  return [indentUnit.of("    "), keymap.of([indentWithTab])];
}

export class Editor {
  view: EditorView;

  constructor(parent: HTMLElement) {
    this.view = new EditorView({
      parent,
      doc: localStorage.getItem(DRAFT_KEY) ?? "",
      extensions: [
        basicSetup,
        python(),
        pythonIndentation(),
        oneDark,
        lintGutter(),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            try {
              localStorage.setItem(DRAFT_KEY, update.state.doc.toString());
            } catch {
              // quota/private mode: drafts stop persisting, typing must not break
            }
          }
        }),
      ],
    });
  }

  get code(): string {
    return this.view.state.doc.toString();
  }

  setCode(code: string): void {
    this.view.dispatch({
      changes: { from: 0, to: this.view.state.doc.length, insert: code },
    });
    this.clearDiagnostics(); // the marked position belonged to the old text
  }

  get isEmpty(): boolean {
    return this.code.trim().length === 0;
  }

  gotoLine(line: number): void {
    const doc = this.view.state.doc;
    const ln = doc.line(Math.min(Math.max(line, 1), doc.lines));
    this.view.dispatch({
      selection: { anchor: ln.from },
      scrollIntoView: true,
    });
    this.view.focus();
  }

  /** Mark where the parser gave up and put the cursor there. The marker
   * outlives the banner, so a student who scrolls away can still find it. */
  showSyntaxError(line: number, col: number, msg: string): void {
    const range = diagnosticRange(this.view.state.doc, line, col);
    this.view.dispatch(setDiagnostics(this.view.state, [
      { from: range.from, to: range.to, severity: "error", message: msg },
    ]));
    this.view.dispatch({ selection: { anchor: range.from }, scrollIntoView: true });
    this.view.focus();
  }

  clearDiagnostics(): void {
    this.view.dispatch(setDiagnostics(this.view.state, []));
  }
}
