#!/usr/bin/env python3
"""Step 3 — Discovery (needs YOUTUBE_API_KEY).

Search YouTube by topic, not person. Rank by outlier score = a video's views ÷ the
channel's average views per video (channel total views ÷ video count). A small channel
getting 10× its normal views usually signals unusually good explaining.

Also runs critic searches ("<topic> overhyped", "... doesn't work", "... six months later")
so the skeptics show up on purpose.

  python discover.py "trending GitHub AI repos"
  python discover.py --topics-file topics.txt --days 60
  python discover.py "AI agents" --no-critics --max 25

Quota: each search costs 100 units (default daily quota 10,000). One topic with critics
= 4 searches + 2 cheap stat calls ≈ 402 units.

Output: out/discovery/<date>_<slug>.json (input for quality.py) + .md (to read).
"""
import argparse
import datetime as dt
import json
import re
import sys

import requests

from bunny import config

API = "https://www.googleapis.com/youtube/v3"
CRITIC_SUFFIXES = ["overhyped", "doesn't work", "six months later"]


def yt(path, **params):
    if not config.YOUTUBE_API_KEY:
        sys.exit("YOUTUBE_API_KEY is not set. Add it to .env (see README > Keys needed).")
    r = requests.get(f"{API}/{path}", params={**params, "key": config.YOUTUBE_API_KEY}, timeout=30)
    if r.status_code == 403:
        sys.exit(f"YouTube API refused the request (quota or key): {r.text[:300]}")
    r.raise_for_status()
    return r.json()


def search(q, days, max_results):
    after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = yt("search", part="snippet", q=q, type="video", order="relevance",
             publishedAfter=after, maxResults=min(max_results, 50), relevanceLanguage="en")
    return [i["id"]["videoId"] for i in res.get("items", [])]


def _chunks(xs, n=50):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def iso_seconds(d):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def outlier_score(video_views, channel_views, channel_videos):
    """views ÷ channel's average views per video. None when the channel hides stats."""
    if not channel_videos or not channel_views:
        return None
    avg = channel_views / channel_videos
    return round(video_views / avg, 2) if avg else None


def enrich(video_ids):
    vids = {}
    for chunk in _chunks(video_ids):
        for v in yt("videos", part="snippet,statistics,contentDetails", id=",".join(chunk)).get("items", []):
            vids[v["id"]] = v
    chan_ids = sorted({v["snippet"]["channelId"] for v in vids.values()})
    chans = {}
    for chunk in _chunks(chan_ids):
        for c in yt("channels", part="snippet,statistics", id=",".join(chunk)).get("items", []):
            chans[c["id"]] = c
    rows = []
    for vid, v in vids.items():
        c = chans.get(v["snippet"]["channelId"], {})
        cs, vs = c.get("statistics", {}), v.get("statistics", {})
        views = int(vs.get("viewCount", 0))
        subs = int(cs.get("subscriberCount", 0)) if not cs.get("hiddenSubscriberCount") else 0
        ch_views, ch_count = int(cs.get("viewCount", 0)), int(cs.get("videoCount", 0))
        rows.append({
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": v["snippet"]["title"],
            "published": v["snippet"]["publishedAt"][:10],
            "duration_s": iso_seconds(v.get("contentDetails", {}).get("duration")),
            "views": views,
            "likes": int(vs.get("likeCount", 0)),
            "comments": int(vs.get("commentCount", 0)),
            "channel_id": v["snippet"]["channelId"],
            "channel": v["snippet"]["channelTitle"],
            "channel_url": f"https://www.youtube.com/channel/{v['snippet']['channelId']}",
            "subs": subs,
            "channel_avg_views": round(ch_views / ch_count) if ch_count else None,
            "outlier": outlier_score(views, ch_views, ch_count),
            "views_per_sub": round(views / subs, 2) if subs else None,
        })
    return rows


def run_topic(topic, days, max_results, critics, min_seconds):
    queries = [("main", topic)] + ([("critic", f"{topic} {s}") for s in CRITIC_SUFFIXES] if critics else [])
    found = {}
    for role, q in queries:
        print(f"  search[{role}]: {q}")
        for vid in search(q, days, max_results):
            found.setdefault(vid, {"role": role, "query": q})
    rows = enrich(list(found))
    for r in rows:
        r.update(found[r["video_id"]])
    rows = [r for r in rows if r["duration_s"] >= min_seconds]  # drop Shorts by default
    rows.sort(key=lambda r: (r["outlier"] or 0), reverse=True)
    return rows


def write_report(topic, rows):
    out = config.OUT / "discovery"
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:50]
    base = out / f"{dt.date.today():%Y-%m-%d}_{slug}"
    base.with_suffix(".json").write_text(json.dumps({"topic": topic, "results": rows}, indent=2))
    lines = [f"# Discovery: {topic}", f"_{dt.date.today()} · {len(rows)} videos · sorted by outlier score_", ""]
    for role, label in (("main", "Top explainers"), ("critic", "Critics / reality checks")):
        lines += [f"## {label}", "", "| Outlier | Views | Subs | Channel | Video |", "|---|---|---|---|---|"]
        for r in [x for x in rows if x["role"] == role][:20]:
            o = f"{r['outlier']}×" if r["outlier"] is not None else "–"
            lines.append(f"| {o} | {r['views']:,} | {r['subs']:,} | {r['channel']} | [{r['title']}]({r['url']}) |")
        lines.append("")
    base.with_suffix(".md").write_text("\n".join(lines))
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topics", nargs="*")
    ap.add_argument("--topics-file")
    ap.add_argument("--days", type=int, default=90, help="only videos published in the last N days")
    ap.add_argument("--max", type=int, default=25, help="results per search (max 50)")
    ap.add_argument("--no-critics", action="store_true")
    ap.add_argument("--min-seconds", type=int, default=180, help="drop videos shorter than this (Shorts)")
    a = ap.parse_args()
    topics = list(a.topics)
    if a.topics_file:
        topics += [t.strip() for t in open(a.topics_file) if t.strip() and not t.startswith("#")]
    if not topics:
        topics = ["trending GitHub AI repos"]
    for t in topics:
        print(f"Topic: {t}")
        rows = run_topic(t, a.days, a.max, not a.no_critics, a.min_seconds)
        base = write_report(t, rows)
        print(f"  -> {base}.md / .json ({len(rows)} videos)")


if __name__ == "__main__":
    main()
