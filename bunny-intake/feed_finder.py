#!/usr/bin/env python3
"""Step 1 — Feed finder.

For each roster name with an EMPTY feed cell, find YouTube / podcast / Substack candidates
with key-free lookups (iTunes Search API, Substack search, YouTube results page) and write
them to the sheet. Auto-found links are marked "Confidence: auto — verify", because name
search gets namesakes wrong. Rows that already have links are never touched.

  python feed_finder.py                 # dry run: print suggestions
  python feed_finder.py --write         # write suggestions to empty cells
  python feed_finder.py --seed --write  # write data/feeds_seed.json into empty cells
  python feed_finder.py --only "Gary Marcus"
"""
import argparse
import json

from bunny import config, feeds
from bunny import google as g


def suggest(name: str) -> dict:
    links, notes = {}, []
    q = name.split("(")[0].split("/")[0].strip()
    try:
        yt = feeds.youtube_search_channels(q, limit=3)
        if yt:
            links["YouTube"] = yt[0]["url"]
            notes.append(f"YT top hit '{yt[0]['title']}'")
    except Exception as e:
        notes.append(f"YT search failed ({type(e).__name__})")
    try:
        pods = [p for p in feeds.itunes_search(q, limit=5)
                if q.split()[-1].lower() in f"{p['name']} {p['artist']}".lower()]
        if pods:
            links["Podcast"] = pods[0]["rss"] or pods[0]["apple"]
            notes.append(f"podcast '{pods[0]['name']}'")
    except Exception as e:
        notes.append(f"iTunes failed ({type(e).__name__})")
    try:
        subs = [s for s in feeds.substack_search(q, limit=5)
                if q.split()[-1].lower() in f"{s['name']} {s['author']}".lower()]
        if subs and subs[0]["url"]:
            links["Substack"] = subs[0]["url"]
            notes.append(f"substack '{subs[0]['name']}'")
    except Exception as e:
        notes.append(f"Substack failed ({type(e).__name__})")
    return {**links, "Note": "; ".join(notes)}


def cell_from(entry: dict, confidence: str) -> str:
    body = feeds.format_cell(entry)
    conf = f"Confidence: {entry.get('confidence', confidence)}"
    if entry.get("Note"):
        conf += f" — {entry['Note']}"
    return f"{body}\n{conf}".strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write to the sheet (default: dry run)")
    ap.add_argument("--seed", action="store_true", help="use data/feeds_seed.json instead of searching")
    ap.add_argument("--only", help="just this roster name")
    a = ap.parse_args()

    header, rows = g.read_roster()
    seed = json.loads((config.ROOT / "data" / "feeds_seed.json").read_text()) if a.seed else {}
    for r in rows:
        name = r[config.COL_NAME].strip()
        if a.only and name != a.only:
            continue
        if r.get(config.COL_FEEDS, "").strip():
            print(f"= {name}: already has links, skipping")
            continue
        if a.seed:
            if name not in seed:
                print(f"? {name}: not in seed file")
                continue
            cell = cell_from(seed[name], "seed")
        else:
            cell = cell_from(suggest(name), "auto — verify")
        print(f"+ {name}\n    " + cell.replace("\n", "\n    "))
        if a.write:
            g.write_cell(header, r["_row"], config.COL_FEEDS, cell)
    if not a.write:
        print("\n(dry run — add --write to save to the sheet)")


if __name__ == "__main__":
    main()
