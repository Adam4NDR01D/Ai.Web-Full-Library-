#!/usr/bin/env python3
"""Step 4 — Quality pass (needs a discovery JSON from discover.py + Claude API access).

Takes the top outliers (and top critics) from a discovery run, pulls each transcript,
asks Claude to score clarity / sourcing / balance (1–5) and note writing style, then
adds winners to the roster with Status = "Candidate". Channels already on the roster
are skipped.

  python quality.py out/discovery/2026-11-13_trending-github-ai-repos.json            # dry run
  python quality.py out/discovery/...json --top 8 --critics 4 --write
  python quality.py ... --min-avg 3.7

Output: out/quality/<same name>.md with every score, winners or not.
"""
import argparse
import json
from pathlib import Path

from bunny import config, transcripts
from bunny import google as g

PILLARS = ["Class & power", "East/West", "What gets built", "Resources & energy",
           "Jobs", "Safety", "History & meaning"]

SCHEMA = {
    "type": "object",
    "properties": {
        "clarity": {"type": "integer", "description": "1-5: is the core idea easy to follow for a smart non-expert?"},
        "sourcing": {"type": "integer", "description": "1-5: are claims backed by named sources, data, demos or links?"},
        "balance": {"type": "integer", "description": "1-5: does it give the other side's strongest point fairly?"},
        "camp": {"type": "string", "enum": ["booster", "pragmatist", "skeptic", "safety", "critic", "mixed"]},
        "pillar": {"type": "string", "enum": PILLARS},
        "claim": {"type": "string", "description": "The core argument in one sentence."},
        "style_note": {"type": "string", "description": "One sentence on writing/explaining style worth learning from (or avoiding)."},
        "red_flags": {"type": "string", "description": "Hype, undisclosed sponsorship, factual errors; empty if none."},
        "recommend": {"type": "boolean", "description": "Worth following as a regular source?"},
    },
    "required": ["clarity", "sourcing", "balance", "camp", "pillar", "claim", "style_note", "red_flags", "recommend"],
    "additionalProperties": False,
}

SYSTEM = """You vet YouTube sources for a research roster behind a fair-minded AI explainer show.
The show's rule: every view gets its opposite, every claim is sourced, critics get their best shot.
Score the transcript strictly — a 5 is rare. Clickbait energy with thin evidence scores low on
sourcing even if it's entertaining. A critic who checks whether a hyped thing actually got used
scores high on balance. Judge only from the transcript."""


def score(client, item, transcript):
    msg = (f"Topic searched: {item.get('query')}\nVideo: {item['title']}\nChannel: {item['channel']} "
           f"({item['subs']:,} subs; this video {item['views']:,} views, outlier {item['outlier']}x)\n\n"
           f"<transcript>\n{transcript}\n</transcript>")
    resp = client.beta.messages.create(
        model=config.JUDGE_MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": msg}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if the model declines, the API retries on a fallback model
    )
    if resp.stop_reason == "refusal":
        return None
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("discovery_json")
    ap.add_argument("--top", type=int, default=8, help="top-N main results by outlier score")
    ap.add_argument("--critics", type=int, default=4, help="top-N critic results")
    ap.add_argument("--min-avg", type=float, default=3.7, help="winner threshold (mean of 3 scores)")
    ap.add_argument("--write", action="store_true", help="append winners to the sheet")
    a = ap.parse_args()

    import anthropic
    client = anthropic.Anthropic()

    data = json.loads(Path(a.discovery_json).read_text())
    rows = data["results"]
    pick = ([r for r in rows if r["role"] == "main"][:a.top]
            + [r for r in rows if r["role"] == "critic"][:a.critics])

    header, roster = g.read_roster()
    roster_names = {r[config.COL_NAME].strip().lower() for r in roster}
    roster_feeds = "\n".join(r.get(config.COL_FEEDS, "") for r in roster)  # to match channel ids/urls

    report, winners, seen_channels = [], [], set()
    for it in pick:
        if it["channel_id"] in seen_channels:
            continue
        seen_channels.add(it["channel_id"])
        print(f"- {it['channel']}: {it['title'][:70]}")
        tr = transcripts.youtube_transcript(it["video_id"])
        if not tr:
            report.append({**it, "skipped": "no transcript"})
            continue
        s = score(client, it, tr)
        if s is None:
            report.append({**it, "skipped": "model declined"})
            continue
        avg = round((s["clarity"] + s["sourcing"] + s["balance"]) / 3, 2)
        rec = {**it, **s, "avg": avg}
        report.append(rec)
        print(f"    clarity {s['clarity']} · sourcing {s['sourcing']} · balance {s['balance']} → {avg}"
              f"{'  ✓' if avg >= a.min_avg and s['recommend'] else ''}")
        known = it["channel"].lower() in roster_names or it["channel_id"] in roster_feeds
        if avg >= a.min_avg and s["recommend"] and not known:
            winners.append(rec)

    out = config.OUT / "quality"
    out.mkdir(parents=True, exist_ok=True)
    md = out / (Path(a.discovery_json).stem + ".md")
    lines = [f"# Quality pass: {data['topic']}", "",
             "| Avg | C | S | B | Camp | Channel | Video | Claim | Style |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(report, key=lambda r: r.get("avg", 0), reverse=True):
        if "skipped" in r:
            lines.append(f"| – | | | | | {r['channel']} | [{r['title']}]({r['url']}) | _{r['skipped']}_ | |")
        else:
            lines.append(f"| {r['avg']} | {r['clarity']} | {r['sourcing']} | {r['balance']} | {r['camp']} | "
                         f"{r['channel']} | [{r['title']}]({r['url']}) | {r['claim']} | {r['style_note']} |")
    md.write_text("\n".join(lines))
    print(f"\nReport: {md}\nWinners: {len(winners)}")

    for w in winners:
        record = {
            config.COL_NAME: w["channel"],
            config.COL_PILLAR: w["pillar"],
            config.COL_STANCE: w["camp"],
            config.COL_TYPE: "YouTube",
            config.COL_FEEDS: f"YouTube: {w['channel_url']}\nConfidence: auto — from discovery",
            config.COL_WHY: (f"{w['claim']} | C{w['clarity']}/S{w['sourcing']}/B{w['balance']} | "
                             f"style: {w['style_note']} | sample: {w['url']}"),
            config.COL_STATUS: "Candidate",
            config.COL_SOURCE: f"Discovery: {data['topic']} ({w['role']}, outlier {w['outlier']}×)",
        }
        print(f"  + Candidate: {w['channel']} ({w['avg']})")
        if a.write:
            g.append_row(header, record)
    if winners and not a.write:
        print("(dry run — add --write to append candidates to the sheet)")


if __name__ == "__main__":
    main()
