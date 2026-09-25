#!/usr/bin/env bash
# One-time (and re-runnable) setup on macOS: install a launchd agent that runs
# tools/publish.sh from THIS checkout once a day, then print the remaining steps.
#
#   ./tools/setup.sh            # install/refresh the launchd agent + print next steps
#   DRY_RUN=1 ./tools/setup.sh  # only print the rendered plist + next steps
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "setup: launchd is macOS-only — on other systems schedule tools/publish.sh with cron/systemd" >&2
  exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.$(whoami).aitokenburn"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

PLIST="$(sed \
  -e "s|__LABEL__|$LABEL|" \
  -e "s|__PUBLISH_SH__|$REPO/tools/publish.sh|" \
  -e "s|__LOG__|$HOME/Library/Logs/aitokenburn.log|" \
  -e "s|__ERR_LOG__|$HOME/Library/Logs/aitokenburn.err.log|" \
  "$REPO/tools/aitokenburn.plist.template")"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "setup: [dry-run] would write $DEST:"
  echo "$PLIST"
else
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  printf '%s\n' "$PLIST" > "$DEST"
  launchctl bootout "gui/$(id -u)" "$DEST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$DEST"
  echo "setup: installed + loaded $DEST (runs tools/publish.sh daily at 10:00)"
fi

# <owner>/<repo> of this checkout's GitHub origin, for the Pages + embed steps.
ORIGIN="$(git -C "$REPO" remote get-url origin 2>/dev/null || true)"
SLUG="$(printf '%s' "$ORIGIN" | sed -nE 's#^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+)/?$#\2#p' | sed -E 's#\.git$##')"
if [[ -z "$SLUG" ]]; then
  echo "setup: origin ('$ORIGIN') is not a GitHub repo — using OWNER/REPO placeholders below" >&2
  SLUG="OWNER/REPO"
fi
OWNER="${SLUG%%/*}"
NAME="${SLUG#*/}"
PAGES="https://$(printf '%s' "$OWNER" | tr '[:upper:]' '[:lower:]').github.io/$NAME/"
RAW="https://raw.githubusercontent.com/$SLUG/output/assets"

cat <<EOF

Next steps:
  1. Publish once now (creates + pushes the 'output' branch; --fresh starts your
     history from zero — use --restore instead if this fork already has one):
       $REPO/tools/publish.sh --fresh
  2. Enable GitHub Pages: Settings → Pages → Deploy from a branch → 'output', folder '/'.
     Or with the gh CLI:
       gh api -X POST repos/$SLUG/pages -f 'source[branch]=output' -f 'source[path]=/'
     Your dashboard: $PAGES
  3. Paste into your profile README (github.com/$OWNER/$OWNER/README.md):

<a href="$PAGES">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="$RAW/overview-dark.svg">
    <img alt="AI token burn" src="$RAW/overview-light.svg">
  </picture>
</a>
EOF
