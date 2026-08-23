/** CodeMirror 6 python editor. */

import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView, basicSetup } from "codemirror";

const DRAFT_KEY = "dl_draft";

export class Editor {
  view: EditorView;

  constructor(parent: HTMLElement) {
    this.view = new EditorView({
      parent,
      doc: localStorage.getItem(DRAFT_KEY) ?? "",
      extensions: [
        basicSetup,
        python(),
        oneDark,
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
}
