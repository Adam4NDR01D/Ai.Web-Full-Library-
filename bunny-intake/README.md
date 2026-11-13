# bunny-intake

A small discovery pipeline for the Bunny Network research engine. It implements the "Research intake & discovery plan" section of the Bunny Blueprint (Production & Factory tab). It uses plain Python scripts and no agent framework.

| Step | Script | Needs | What it does |
|---|---|---|---|
| 1 | `feed_finder.py` | Google login | Fills empty **Feed links** cells on the roster sheet with YouTube, podcast and Substack links |
| 2 | `feed_watcher.py` | Google login | Weekly: pulls new videos, episodes and posts and saves transcripts or text as Google Docs in Drive › **Bunny Intake** for NotebookLM |
| 3 | `discover.py` | **YouTube API key** | Searches YouTube by topic, ranks by outlier score, and runs "overhyped / doesn't work / six months later" critic searches |
| 4 | `quality.py` | Claude API + Google login | Claude scores sample transcripts on clarity, sourcing and balance; winners are appended to the sheet with Status = `Candidate` |

## 🔑 Waiting on Adam

- [ ] **YouTube Data API v3 key for step 3.** To get one: Google Cloud console → new project "bunny-intake" → APIs & Services → Library → enable **YouTube Data API v3** → Credentials → Create API key → restrict it to that API. It's free (10,000 units/day; one topic with critics uses about 400). Put it in `.env` as `YOUTUBE_API_KEY=...`.
- [ ] **Claude API access for step 4.** Use `ant auth login`, or `ANTHROPIC_API_KEY` in `.env`. The default model is `claude-opus-5-5` at medium effort, with server-side refusal fallback enabled. Override it with `BUNNY_JUDGE_MODEL`.
- [ ] **A Google OAuth client for steps 1, 2 and 4.** Use the same Cloud project → enable the Sheets API and Drive API → Credentials → OAuth client ID → *Desktop app* → download it as `credentials.json` into this folder. The first run opens a browser to log in. Scopes are Sheets plus `drive.file`, so the app can only see files it created.

## Setup (Mac)

```bash
mkdir -p ~/DEV && cp -R bunny-intake ~/DEV/      # or clone the repo and symlink the folder
cd ~/DEV/bunny-intake
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # then fill in the keys
python tests/test_offline.py                      # 9 offline checks, no network needed
```

## Run

```bash
python feed_finder.py                    # dry run: suggest links for rows whose cell is empty
python feed_finder.py --write            # write them; marked "Confidence: auto — verify"

python feed_watcher.py --dry-run --since 14    # see what's new without saving
python feed_watcher.py --since 14              # first real run; later runs use "since last run"

python discover.py "trending GitHub AI repos"  # or: --topics-file topics.txt
python quality.py out/discovery/<date>_trending-github-ai-repos.json           # dry run
python quality.py out/discovery/<date>_trending-github-ai-repos.json --write   # add Candidates
```

**Weekly schedule.** Run `crontab -e` and add this line for Mondays at 6:40am:

```
40 6 * * 1 cd ~/DEV/bunny-intake && .venv/bin/python feed_watcher.py >> out/watcher.log 2>&1
```

Then in NotebookLM: **Add source → Google Drive → Bunny Intake**. Each week makes one Doc per person (`2026-W46 — Gary Marcus`). Bundling by person and week keeps you under NotebookLM's per-notebook source limit.

## How the sheet cell works

The **Feed links** column holds one label per line. You can edit it by hand, and the scripts read it back:

```
YouTube: https://www.youtube.com/@rileybrownai
Podcast: https://podcasts.apple.com/podcast/id1826127218
Substack: https://garymarcus.substack.com | https://second.substack.com
Confidence: high — any note (this line is ignored by the watcher)
```

- **YouTube:** any channel URL (`@handle`, `/channel/UC…`). It is turned into the public RSS feed, so no key is needed.
- **Podcast:** an Apple Podcasts URL (turned into RSS through the free iTunes lookup) or a direct RSS URL.
- **Substack:** any Substack, blog or feed URL. Non-Substack sites get their feed auto-discovered.

## Design notes and limits

- **Outlier score** = video views ÷ the channel's average views per video (channel total views ÷ video count). `views_per_sub` is in the JSON too.
- **Shorts** (under 180s) are dropped from discovery by default (`--min-seconds`).
- **Podcasts without a published transcript** get show notes plus the audio link. NotebookLM can take the audio directly. Whisper is not wired in yet; add it once the volume is worth it.
- **YouTube transcripts** come from `youtube-transcript-api`. YouTube rate-limits heavy scraping, which weekly volume won't hit.
- **The Batch** (Andrew Ng) has no RSS. The watcher logs it as unreadable; drop that line from his cell if the warning annoys you.
- `data/feeds_seed.json` is the step-1 research snapshot (2026-11-13). After that, the sheet is the source of truth.
- Shares the "trending GitHub AI repos" topic with Repo Radar. Point Repo Radar's output at `topics.txt` if you want them coupled.
