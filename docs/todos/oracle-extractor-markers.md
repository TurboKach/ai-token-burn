# Oracle extractor can't find the /stats engine markers

## What
`python3 tools/verify_against_app.py` exits 1 on the installed Claude.app (seen 2026-09-25) with
"Could not locate the /stats engine markers in this Claude version — the extractor needs updating
for this release". `build_oracle()` looks for `const oKr="<synthetic>"` and `let LV=null,ceA=null`
in `.vite/build/index.js` of the extracted app.asar. Those minified identifiers changed in a later
app release. The failure happens before `engine.compute_claude()` runs.

## Why
The oracle is the "verify" half of reimplement-and-verify: without it, a change in the app's
/stats algorithm (or a regression in engine.py) goes undetected.

## Context
- Found while landing per-day records (branch `feat/per-day-records`). The fields the oracle
  compares were confirmed unchanged by diffing old vs new engine output on a frozen log clone,
  but not against the app.
- Fix: locate the /stats aggregation function (EKr equivalent) and its helpers in the new bundle,
  update the start/end markers, the `aKr()` cache-bypass replacement and the entry-point name
  (ideally anchored on stable strings, not minified names), then rerun and confirm a 1:1 match.

## Depends
Nothing.

## Effort
Small to medium: about an hour of bundle spelunking per app release that renames the helpers.
