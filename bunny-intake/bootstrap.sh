#!/usr/bin/env bash
# One command for everything after the Google Cloud clicks:
#   bash bootstrap.sh
# Safe to re-run. Each step skips itself if already done, and the script stops with a
# clear message at the first thing that's actually missing.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
stop() { printf '\n\033[31m■ %s\033[0m\n' "$*"; exit 1; }

say "Python env"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
python tests/test_offline.py >/dev/null && echo "offline tests: ok"

say "Google login (Sheets + Drive)"
[ -f credentials.json ] || {
  dl=$(ls -t ~/Downloads/client_secret_*.json 2>/dev/null | head -1 || true)
  [ -n "$dl" ] && mv "$dl" credentials.json && echo "moved $dl -> credentials.json"
}
[ -f credentials.json ] || stop "No credentials.json yet. Download the Desktop OAuth client JSON from Google Cloud, then re-run."
python feed_finder.py | tail -3          # first run opens the browser login once

say "Feed watcher: first pull (last 14 days) -> Drive 'Bunny Intake'"
if [ -f state.json ]; then python feed_watcher.py; else python feed_watcher.py --since 14; fi

say "Discovery"
grep -q '^YOUTUBE_API_KEY=.\+' .env || stop "YOUTUBE_API_KEY is empty in .env. Paste the key there, then re-run."
python discover.py --topics-file topics.txt

say "Quality pass (dry run: nothing is written to the sheet)"
latest=$(ls -t out/discovery/*.json | head -1)
if grep -q '^ANTHROPIC_API_KEY=.\+' .env || (command -v ant >/dev/null && ant auth status >/dev/null 2>&1); then
  python quality.py "$latest"
  echo; echo "To add the winners to the sheet:  .venv/bin/python quality.py $latest --write"
else
  echo "Skipped: no Claude API access yet (run 'ant auth login' or set ANTHROPIC_API_KEY in .env)."
fi

say "Weekly schedule"
line="40 6 * * 1 cd $PWD && .venv/bin/python feed_watcher.py >> out/watcher.log 2>&1"
if crontab -l 2>/dev/null | grep -qF "feed_watcher.py"; then
  echo "cron already set"
else
  (crontab -l 2>/dev/null; echo "$line") | crontab - && echo "added: Mondays 6:40am"
fi

say "Done. Reports are in out/discovery/ and out/quality/"
