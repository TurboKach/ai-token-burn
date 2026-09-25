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
#   ./tools/publish.sh --restore  # recreate a missing data/stats.json: from origin/output
#                                 # (new machine), else from this branch's git history
#                                 # (upgrading from the layout that committed data/)
#   ./tools/publish.sh --fresh    # first publish of a new fork: start history from zero
#
# With data/stats.json missing, a plain run refuses to start fresh when origin/output
# or this branch's history holds a prior snapshot — pick --restore or --fresh.
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

# Last commit on this branch's own (first-parent) line that wrote data/stats.json, from
# before data/ was untracked. First-parent keeps a fork on its own daily commits rather
# than upstream's merged-in ones.
history_commit() {
  git log --first-parent -1 --diff-filter=AM --format=%H -- data/stats.json
}

MODE="${1:-}"
if [[ "$MODE" == "--restore" || "$MODE" == "--fresh" ]] && [[ -e data/stats.json ]]; then
  echo "publish: data/stats.json already exists — refusing $MODE over local history" >&2
  exit 1
fi

if [[ "$MODE" == "--restore" ]]; then
  if remote_has_branch; then
    fetch_branch
    SRC="origin/$BRANCH"
  elif SHA="$(history_commit)" && [[ -n "$SHA" ]]; then
    SRC="$SHA"
  else
    echo "publish: no '$BRANCH' branch on origin and no data/stats.json in git history — nothing to restore" >&2
    exit 1
  fi
  mkdir -p data
  git show "$SRC:data/stats.json" > data/stats.json.tmp
  mv data/stats.json.tmp data/stats.json
  echo "publish: restored data/stats.json from $SRC"
  exit 0
fi

# Never silently start fresh over a prior snapshot: that would drop every day whose raw
# logs are already pruned. Adopting one is never automatic either — a new fork's history
# carries the upstream owner's data — so the user picks --restore or --fresh.
if [[ "$MODE" != "--fresh" && ! -e data/stats.json ]]; then
  if remote_has_branch; then
    echo "publish: data/stats.json is missing but origin has a '$BRANCH' branch with your history." >&2
    echo "publish: new machine? run: tools/publish.sh --restore" >&2
    exit 1
  elif [[ -n "$(history_commit)" ]]; then
    echo "publish: data/stats.json is missing but this branch's git history has a committed snapshot." >&2
    echo "publish: upgrading from the committed-data layout? run: tools/publish.sh --restore  (recovers it from git history)" >&2
    echo "publish: brand-new fork (that history is upstream's data)? run: tools/publish.sh --fresh" >&2
    exit 1
  fi
fi

python3 collect.py        # writes data/stats.json + docs/data/stats.json
python3 render_hero.py     # writes assets/overview-{light,dark}.svg
python3 themes.py          # writes docs/themes.css from the active theme

# Set up the publish worktree on branch `output` if it isn't there yet.
HAS_REMOTE=0
if remote_has_branch; then HAS_REMOTE=1; fetch_branch; fi
if [[ ! -e "$OUT" ]]; then
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
fi
# Every git command below runs in $OUT; if it isn't its own worktree on `output`, git
# would resolve the enclosing code checkout instead — so refuse.
if [[ ! -d "$OUT" || "$(git -C "$OUT" rev-parse --show-toplevel 2>/dev/null)" != "$(cd "$OUT" && pwd -P)" \
      || "$(git -C "$OUT" symbolic-ref -q --short HEAD)" != "$BRANCH" ]]; then
  echo "publish: $OUT is not a git worktree on branch '$BRANCH' — move it aside and rerun" >&2
  exit 1
fi
if [[ $HAS_REMOTE == 1 ]]; then
  git -C "$OUT" merge -q --ff-only "origin/$BRANCH"
fi

# Only the static dashboard + generated artifacts, at the paths Pages serves: <src> <dest>.
FILES=(docs/index.html index.html docs/app.js app.js docs/flame.js flame.js
       docs/styles.css styles.css docs/themes.css themes.css docs/.nojekyll .nojekyll
       data/stats.json data/stats.json)
for svg in assets/overview-light.svg assets/overview-dark.svg; do
  if [[ -f "$svg" ]]; then FILES+=("$svg" "$svg"); fi
done

# Only these paths are compared, staged and committed — a stray file in $OUT never ships.
CHANGED=()
for ((i = 0; i < ${#FILES[@]}; i += 2)); do
  src="${FILES[i]}" dest="${FILES[i+1]}"
  if ! git -C "$OUT" cat-file -e "HEAD:$dest" 2>/dev/null \
     || ! git -C "$OUT" show "HEAD:$dest" | cmp -s - "$src"; then CHANGED+=("$dest"); fi
done

if [[ ${#CHANGED[@]} -eq 0 ]]; then
  echo "publish: no changes — nothing to commit"
  exit 0
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "publish: [dry-run] would commit + push to '$BRANCH':"
  printf '  %s\n' "${CHANGED[@]}"
  exit 0
fi

mkdir -p "$OUT/data" "$OUT/assets"
for ((i = 0; i < ${#FILES[@]}; i += 2)); do cp "${FILES[i]}" "$OUT/${FILES[i+1]}"; done
git -C "$OUT" add -- "${CHANGED[@]}"
git -C "$OUT" commit -q -m "chore: daily token-burn refresh ($(date +%Y-%m-%d))" -- "${CHANGED[@]}"
git -C "$OUT" push -q -u origin "$BRANCH"
echo "publish: pushed daily refresh to '$BRANCH'"
