#!/usr/bin/env bash
# Daily token-burn refresh: recompute stats from local logs, re-render the hero
# SVGs, and publish them to the `output` branch (served by GitHub Pages; the
# profile README embeds its SVGs). Run daily by the launchd agent that
# tools/setup.sh installs; safe to run by hand too.
#
# The code branch is never touched: generated files are committed in a separate
# git worktree of branch `output` at .output/ (gitignored). Your local
# data/stats.json (also gitignored) is the accumulation state.
#
#   ./tools/publish.sh            # refresh, commit to `output` if changed, push
#   DRY_RUN=1 ./tools/publish.sh  # refresh + show what WOULD change in `output`, no commit/push
#   ./tools/publish.sh --restore  # new machine: recreate data/stats.json from origin/output
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

BRANCH=output
OUT="$REPO/.output"

# True when origin has the branch; false when it doesn't; aborts if origin is unreachable.
remote_has_branch() {
  local rc=0
  git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null || rc=$?
  [[ $rc -eq 0 || $rc -eq 2 ]] || { echo "publish: cannot reach origin" >&2; exit 1; }
  [[ $rc -eq 0 ]]
}

fetch_branch() {
  git fetch -q origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
}

if [[ "${1:-}" == "--restore" ]]; then
  if [[ -e data/stats.json ]]; then
    echo "publish: data/stats.json already exists — refusing to overwrite local history" >&2
    exit 1
  fi
  remote_has_branch || { echo "publish: origin has no '$BRANCH' branch — nothing to restore" >&2; exit 1; }
  fetch_branch
  mkdir -p data
  git show "origin/$BRANCH:data/stats.json" > data/stats.json.tmp
  mv data/stats.json.tmp data/stats.json
  echo "publish: restored data/stats.json from origin/$BRANCH"
  exit 0
fi

python3 collect.py        # writes data/stats.json + docs/data/stats.json
python3 render_hero.py     # writes assets/overview-{light,dark}.svg
python3 themes.py          # writes docs/themes.css from the active theme

# Set up the publish worktree on branch `output` if it isn't there yet.
HAS_REMOTE=0
if remote_has_branch; then HAS_REMOTE=1; fetch_branch; fi
if ! git -C "$OUT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git worktree prune
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git worktree add -q "$OUT" "$BRANCH"
  elif [[ $HAS_REMOTE == 1 ]]; then
    git worktree add -q --track -b "$BRANCH" "$OUT" "origin/$BRANCH"
  else
    # First publish ever: an orphan branch holding only generated files.
    git worktree add -q --detach "$OUT"
    git -C "$OUT" checkout -q --orphan "$BRANCH"
    git -C "$OUT" rm -rfq .
  fi
elif [[ $HAS_REMOTE == 1 ]]; then
  git -C "$OUT" merge -q --ff-only "origin/$BRANCH"
fi

# Only the static dashboard + generated artifacts, at the paths Pages serves.
mkdir -p "$OUT/data" "$OUT/assets"
cp docs/index.html docs/app.js docs/flame.js docs/styles.css docs/themes.css docs/.nojekyll "$OUT/"
cp data/stats.json "$OUT/data/stats.json"
for svg in assets/overview-light.svg assets/overview-dark.svg; do
  if [[ -f "$svg" ]]; then cp "$svg" "$OUT/$svg"; fi
done

if [[ -z "$(git -C "$OUT" status --porcelain --untracked-files=all)" ]]; then
  echo "publish: no changes — nothing to commit"
  exit 0
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "publish: [dry-run] would commit + push to '$BRANCH':"
  git -C "$OUT" status --porcelain --untracked-files=all
  exit 0
fi

git -C "$OUT" add -A .
git -C "$OUT" commit -q -m "chore: daily token-burn refresh ($(date +%Y-%m-%d))"
git -C "$OUT" push -q -u origin "$BRANCH"
echo "publish: pushed daily refresh to '$BRANCH'"
