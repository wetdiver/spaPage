#!/usr/bin/env bash
# Turns the monitor report into a GitHub issue, which GitHub emails to you.
#  - new problem          -> open an issue (email)
#  - same problem again   -> stay quiet (no hourly spam)
#  - problem changed      -> add a comment (email)
#  - everything OK again  -> comment "all clear" and close the issue (email)
set -uo pipefail

REPORT="${1:-monitor-report.md}"
LABEL="site-alert"
TITLE="⚠️ Problem on sxm-massage-onsite.com"

gh label create "$LABEL" --color D93F0B --description "Problem found by the site monitor" --force >/dev/null 2>&1 || true
open_issue=$(gh issue list --label "$LABEL" --state open --json number --jq '.[0].number // empty')

if [ "${OUTCOME:-failure}" = "success" ]; then
  if [ -n "$open_issue" ]; then
    { echo "✅ **All clear.** Every check passes again, closing this alert."; echo; cat "$REPORT"; } > all-clear.md
    gh issue comment "$open_issue" --body-file all-clear.md
    gh issue close "$open_issue"
  fi
  echo "Site OK."
  exit 0
fi

if [ ! -s "$REPORT" ]; then
  printf '# The site monitor itself crashed\n\nIt stopped before it could check the site. Details: %s\n\n<!-- alert-key: crash -->\n' "${RUN_URL:-}" > "$REPORT"
fi
printf '\n[See this run](%s)\n' "${RUN_URL:-}" >> "$REPORT"

key=$(grep -m1 -oP '(?<=<!-- alert-key: )[0-9a-z]+' "$REPORT" || echo none)

if [ -z "$open_issue" ]; then
  gh issue create --title "$TITLE" --label "$LABEL" --body-file "$REPORT"
  echo "Opened a new alert."
else
  last_key=$(gh issue view "$open_issue" --json body,comments --jq '([.body] + [.comments[].body]) | last' \
             | grep -m1 -oP '(?<=<!-- alert-key: )[0-9a-z]+' || true)
  if [ "$last_key" != "$key" ]; then
    gh issue comment "$open_issue" --body-file "$REPORT"
    echo "Problem changed, added an update to issue #$open_issue."
  else
    echo "Same problem as already reported in issue #$open_issue, staying quiet."
  fi
fi
exit 0
