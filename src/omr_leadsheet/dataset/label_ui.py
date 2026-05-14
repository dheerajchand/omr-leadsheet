#!/usr/bin/env python3
"""Build a one-page HTML labeling UI from labels.csv + crops/.

Renders a scrollable grid: each crop shown at 4x with the classifier's
guess in an input field. You correct the wrong ones, click "Export",
and the page downloads an updated labels.csv. Local-only, no server - 
opens straight from the filesystem.

Usage: dataset_label_ui.py <labeling-dir>
       open <labeling-dir>/label.html
"""
from __future__ import annotations
import base64
import csv
import html as html_lib
import json
import os
import sys


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: dataset_label_ui.py <labeling-dir>", file=sys.stderr)
        sys.exit(2)
    base = sys.argv[1]
    crops_dir = os.path.join(base, "crops")
    csv_path = os.path.join(base, "labels.csv")

    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    # Embed each crop as a base64 data URL so the file is self-contained
    ctx_dir = os.path.join(base, "context")
    items = []
    for r in rows:
        path = os.path.join(crops_dir, r["filename"])
        if not os.path.exists(path):
            continue
        with open(path, "rb") as fp:
            data = base64.b64encode(fp.read()).decode("ascii")
        ctx_url = ""
        ctx_path = os.path.join(ctx_dir, r["filename"])
        if os.path.exists(ctx_path):
            with open(ctx_path, "rb") as fp:
                ctx_url = "data:image/png;base64," + base64.b64encode(fp.read()).decode("ascii")
        items.append({
            "filename": r["filename"],
            "source": r.get("source", ""),
            "audiveris_guess": r.get("audiveris_guess", ""),
            "context": r.get("context", ""),
            "classifier_guess": r.get("classifier_guess", ""),
            "classifier_conf": r.get("classifier_conf", ""),
            "correct_label": r.get("correct_label", ""),
            "data_url": f"data:image/png;base64,{data}",
            "ctx_url": ctx_url,
        })

    items_json = json.dumps(items)
    out_path = os.path.join(base, "label.html")
    html = """<!doctype html>
<meta charset="utf-8">
<title>Chord Label</title>
<style>
  body { font: 14px/1.4 system-ui, sans-serif; background: #1a1a1a; color: #eee; margin: 0; padding: 16px; }
  .toolbar { position: sticky; top: 0; background: #1a1a1a; padding: 8px 0 16px; border-bottom: 1px solid #333; z-index: 10; }
  .toolbar input, .toolbar button { font-size: 14px; padding: 6px 10px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; padding-top: 16px; }
  .card { background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; padding: 10px; }
  .card img.tight { display: block; width: 100%; image-rendering: pixelated; background: #fff; border-radius: 3px; }
  .card details { margin-top: 6px; font-size: 11px; color: #aaa; }
  .card details summary { cursor: pointer; user-select: none; }
  .card details img.ctx { display: block; width: 100%; margin-top: 4px; background: #fff; border-radius: 3px; }
  .meta { font-size: 11px; color: #888; margin-top: 6px; word-break: break-all; }
  .pred { color: #6cf; font-weight: 600; }
  .conf { color: #aaa; }
  .lowconf { color: #f88; }
  input.label { width: 100%; margin-top: 6px; padding: 6px; font-size: 14px;
                background: #1a1a1a; color: #eee; border: 1px solid #555; border-radius: 3px; }
  input.label.modified { border-color: #fc6; background: #2a2a1a; }
  input.label.empty { border-style: dashed; }
  .stats { margin-left: 16px; color: #aaa; }
</style>

<div class="toolbar">
  <button id="accept-all">Accept all classifier guesses</button>
  <button id="accept-high">Accept guesses with conf ≥ 0.85</button>
  <button id="filter-low">Show only low-conf (&lt; 0.7)</button>
  <button id="filter-unlabeled">Show only unlabeled</button>
  <button id="filter-sharp">Show only sharp/aug/dim predictions</button>
  <button id="filter-all">Show all</button>
  <button id="export">Export updated labels.csv</button>
  <span class="stats" id="stats"></span>
</div>

<div class="grid" id="grid"></div>

<script>
const items = ITEMS_JSON;
const grid = document.getElementById("grid");
const stats = document.getElementById("stats");

function render(filterFn) {
  grid.innerHTML = "";
  let shown = 0;
  for (const it of items) {
    if (filterFn && !filterFn(it)) continue;
    shown++;
    const card = document.createElement("div");
    card.className = "card";
    const conf = parseFloat(it.classifier_conf || "0");
    const confClass = conf < 0.7 ? "lowconf" : "";
    card.innerHTML = `
      <img class="tight" src="${it.data_url}">
      ${it.ctx_url ? `<details><summary>show context</summary><img class="ctx" src="${it.ctx_url}"></details>` : ""}
      <div class="meta">
        <span class="pred">${it.classifier_guess || "(none)"}</span>
        <span class="conf ${confClass}">conf ${it.classifier_conf}</span>
        ${it.audiveris_guess ? "· audiveris=" + it.audiveris_guess : ""}
        <br>${it.context}<br>${it.source}
      </div>
      <input class="label ${it.correct_label ? '' : 'empty'}" data-fn="${it.filename}"
        placeholder="label (blank = skip)" value="${it.correct_label || ''}">
    `;
    grid.appendChild(card);
  }
  stats.textContent = `${shown} crops shown · ${items.length} total · ${items.filter(i => i.correct_label).length} labeled`;
}

grid.addEventListener("input", e => {
  if (!e.target.classList.contains("label")) return;
  const fn = e.target.dataset.fn;
  const item = items.find(i => i.filename === fn);
  item.correct_label = e.target.value.trim();
  e.target.classList.toggle("modified", item.correct_label !== item.classifier_guess);
  e.target.classList.toggle("empty", !item.correct_label);
  stats.textContent = stats.textContent.replace(/\\d+ labeled/, items.filter(i => i.correct_label).length + " labeled");
});

document.getElementById("accept-all").onclick = () => {
  for (const it of items) {
    if (!it.correct_label && it.classifier_guess) it.correct_label = it.classifier_guess;
  }
  render();
};
document.getElementById("accept-high").onclick = () => {
  for (const it of items) {
    if (!it.correct_label && it.classifier_guess && parseFloat(it.classifier_conf || "0") >= 0.85) {
      it.correct_label = it.classifier_guess;
    }
  }
  render();
};
document.getElementById("filter-low").onclick = () => render(it => parseFloat(it.classifier_conf || "0") < 0.7);
document.getElementById("filter-unlabeled").onclick = () => render(it => !it.correct_label);
document.getElementById("filter-sharp").onclick = () => render(it => /[#+]|dim|aug/.test(it.classifier_guess || ""));
document.getElementById("filter-all").onclick = () => render();

document.getElementById("export").onclick = () => {
  const fields = ["filename","source","audiveris_guess","context",
                  "classifier_guess","classifier_conf","correct_label"];
  const esc = s => {
    s = (s == null ? "" : String(s));
    return s.includes(",") || s.includes('"') ? '"' + s.replace(/"/g,'""') + '"' : s;
  };
  let csv = fields.join(",") + "\\n";
  for (const it of items) {
    csv += fields.map(f => esc(it[f])).join(",") + "\\n";
  }
  const blob = new Blob([csv], {type: "text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "labels.csv";
  a.click();
};

render();
</script>
"""
    html = html.replace("ITEMS_JSON", items_json)
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Wrote labeling UI → {out_path}")
    print(f"Open it:    open '{out_path}'")
    print()
    print("Workflow:")
    print("  1. Click 'Accept guesses with conf ≥ 0.85' - auto-labels the easy ones")
    print("  2. Click 'Show only low-conf' - review and correct the rest")
    print("  3. Click 'Export updated labels.csv' - saves a new CSV to Downloads")
    print(f"  4. Move that CSV back to: {csv_path}")


if __name__ == "__main__":
    main()
