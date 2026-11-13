#!/usr/bin/env python3
"""Step 2 — Feed watcher (weekly). No YouTube API key needed.

Reads the roster's feed cells, pulls items newer than the last run, and saves the text
(video transcript / podcast transcript or show notes / full post) as Google Docs in the
Drive folder "Bunny Intake", which NotebookLM can add as sources.

One Doc per person per ISO week ("2026-W46 — Gary Marcus") keeps NotebookLM's source
count manageable. Local copies go to out/intake/.

  python feed_watcher.py --dry-run          # list what's new, save nothing, keep state
  python feed_watcher.py                    # fetch, write local + Drive, update state
  python feed_watcher.py --since 14         # first run: look back N days (default 7)
  python feed_watcher.py --local-only       # skip Drive upload
  python feed_watcher.py --only "Gary Marcus"
"""
import argparse
import datetime as dt
import re
import time
from collections import defaultdict

import feedparser

from bunny import config, feeds, state, transcripts
from bunny import google as g

NOW = dt.datetime.now(dt.timezone.utc)


def _when(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return dt.datetime.fromtimestamp(time.mktime(t), dt.timezone.utc) if t else None


def _parse(url):
    d = feedparser.parse(url, agent=config.UA)
    if d.bozo and not d.entries:
        raise RuntimeError(f"unreadable feed: {getattr(d, 'bozo_exception', '')}")
    return d


def collect(person, links, st, since):
    """Yield dicts: kind, title, url, date, text."""
    for url in links.get("YouTube", []):
        cid = feeds.youtube_channel_id(url, st["yt_ids"])
        if not cid:
            print(f"  ! {person}: couldn't resolve channel id for {url}")
            continue
        for e in _parse(feeds.youtube_rss(cid)).entries:
            when = _when(e)
            if when and when >= since:
                yield {"kind": "video", "title": e.title, "url": e.link, "date": when,
                       "fetch": lambda e=e: transcripts.youtube_transcript(transcripts.video_id(e.link))
                       or f"[No transcript available]\n\n{feeds.strip_html(e.get('summary', ''))}"}

    for url in links.get("Podcast", []):
        rss = feeds.podcast_rss(url, st["pod_rss"])
        if not rss:
            print(f"  ! {person}: no RSS for {url}")
            continue
        for e in _parse(rss).entries:
            when = _when(e)
            if when and when >= since:
                yield {"kind": "episode", "title": e.title, "url": e.get("link", rss), "date": when,
                       "fetch": lambda e=e: podcast_text(e)}

    for url in links.get("Substack", []):
        for e in _parse(feeds.text_feed(url)).entries:
            when = _when(e)
            if when and when >= since:
                body = (e.get("content") or [{}])[0].get("value") or e.get("summary", "")
                yield {"kind": "post", "title": e.title, "url": e.link, "date": when,
                       "fetch": lambda b=body: feeds.strip_html(b)}


def podcast_text(e):
    """Prefer a published transcript (podcast:transcript), else show notes + audio link."""
    import requests
    tr = e.get("podcast_transcript")
    tr_url = tr.get("url") if isinstance(tr, dict) else None
    if tr_url:
        try:
            r = requests.get(tr_url, headers={"User-Agent": config.UA}, timeout=30)
            r.raise_for_status()
            return feeds.strip_html(r.text)
        except Exception as ex:
            print(f"    transcript fetch failed: {ex}")
    audio = next((l["href"] for l in e.get("links", []) if l.get("type", "").startswith("audio")), "")
    notes = feeds.strip_html((e.get("content") or [{}])[0].get("value") or e.get("summary", ""))
    return (f"[No published transcript — show notes only. Audio: {audio}]\n"
            f"[To transcribe: drop the audio into NotebookLM directly, or run Whisper]\n\n{notes}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--since", type=int, default=7, help="days to look back when nothing seen yet")
    ap.add_argument("--only")
    a = ap.parse_args()

    st = state.load()
    header, rows = g.read_roster()
    week = NOW.strftime("%G-W%V")
    bundles = defaultdict(list)  # person -> [item text]
    folder = None

    for r in rows:
        person = r[config.COL_NAME].strip()
        if a.only and person != a.only:
            continue
        links = feeds.parse_cell(r.get(config.COL_FEEDS, ""))
        if not links:
            continue
        last = st["seen"].get(person, {}).get("_last_run")
        since = dt.datetime.fromisoformat(last) if last else NOW - dt.timedelta(days=a.since)
        print(f"- {person} (since {since:%Y-%m-%d})")
        seen = st["seen"].setdefault(person, {})
        try:
            for item in collect(person, links, st, since):
                if item["url"] in seen:
                    continue
                print(f"    {item['kind']:7} {item['date']:%Y-%m-%d}  {item['title'][:80]}")
                if a.dry_run:
                    continue
                text = item["fetch"]()
                bundles[person].append(
                    f"## {item['title']}\n{item['kind']} · {item['date']:%Y-%m-%d} · {item['url']}\n\n{text}\n")
                seen[item["url"]] = item["date"].isoformat()
        except Exception as e:
            print(f"  ! {person}: {type(e).__name__}: {e}")
            continue
        if not a.dry_run:
            seen["_last_run"] = NOW.isoformat()

    if a.dry_run:
        print("\n(dry run — nothing saved, state unchanged)")
        return

    out_dir = config.OUT / "intake" / week
    out_dir.mkdir(parents=True, exist_ok=True)
    for person, items in bundles.items():
        r = next(x for x in rows if x[config.COL_NAME].strip() == person)
        title = f"{week} — {person}"
        head = (f"# {title}\nPillar: {r.get(config.COL_PILLAR, '')} | Stance: {r.get(config.COL_STANCE, '')}\n"
                f"Collected {NOW:%Y-%m-%d} by bunny-intake. {len(items)} item(s).\n\n")
        text = head + "\n---\n\n".join(items)
        safe = re.sub(r"[^\w\- ]+", "", person)[:60]
        (out_dir / f"{safe}.md").write_text(text)
        if not a.local_only:
            folder = folder or g.ensure_folder()
            doc = g.upload_text_as_doc(folder, title, text)
            print(f"  ↑ {title} -> {doc.get('webViewLink')}")
    state.save(st)
    print(f"\nDone: {sum(map(len, bundles.values()))} new item(s) for {len(bundles)} people. Local copies: {out_dir}")


if __name__ == "__main__":
    main()
