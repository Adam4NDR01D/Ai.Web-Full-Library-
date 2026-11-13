"""Offline checks — no network, no keys.  Run: python -m pytest -q  (or python tests/test_offline.py)"""
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import feedparser  # noqa: E402

from bunny import feeds  # noqa: E402
import discover  # noqa: E402

YT_XML = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>abcdefghijk</yt:videoId><title>Test video</title>
<link rel="alternate" href="https://www.youtube.com/watch?v=abcdefghijk"/><published>2026-11-10T12:00:00+00:00</published></entry></feed>"""

POD_XML = """<?xml version="1.0"?><rss version="2.0" xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><title>P</title>
<item><title>Ep 1</title><pubDate>Mon, 10 Nov 2026 12:00:00 GMT</pubDate>
<enclosure url="https://x/ep1.mp3" type="audio/mpeg"/>
<podcast:transcript url="https://x/ep1.vtt" type="text/vtt"/><description>&lt;p&gt;Show notes&lt;/p&gt;</description></item>
</channel></rss>"""


def test_cell_roundtrip_with_sheet_text():
    cell = json.loads((ROOT / "data" / "feeds_seed.json").read_text())
    for name, e in cell.items():
        if name.startswith("_"):
            continue
        txt = feeds.format_cell(e) + f"\nConfidence: {e['confidence']} — {e.get('Note', '')}"
        parsed = feeds.parse_cell(txt)
        for k in ("YouTube", "Podcast", "Substack"):
            if e.get(k):
                assert parsed[k] == [u.strip() for u in e[k].split("|")], (name, k, parsed)
            else:
                assert k not in parsed, (name, k)


def test_confidence_line_is_not_a_feed():
    assert feeds.parse_cell("Confidence: low — talks at https://ted.com") == {}


def test_youtube_rss_parse():
    d = feedparser.parse(YT_XML)
    assert d.entries[0].link.endswith("abcdefghijk")
    assert feeds.youtube_rss("UC" + "x" * 22).endswith("channel_id=UC" + "x" * 22)


def test_channel_id_from_channel_url_needs_no_network():
    cid = "UC2m77KGMIKZCD0Kw35-4shQ"
    assert feeds.youtube_channel_id(f"https://www.youtube.com/channel/{cid}", {}) == cid


def test_podcast_transcript_tag_and_rss_passthrough():
    e = feedparser.parse(POD_XML).entries[0]
    tr = e.get("podcast_transcript")
    assert isinstance(tr, dict) and tr.get("url") == "https://x/ep1.vtt"
    assert feeds.podcast_rss("https://media.rss.com/zeihan/feed.xml", {}) == "https://media.rss.com/zeihan/feed.xml"


def test_text_feed_rules():
    assert feeds.text_feed("https://garymarcus.substack.com") == "https://garymarcus.substack.com/feed"
    assert feeds.text_feed("https://simonwillison.net/atom/entries/") == "https://simonwillison.net/atom/entries/"


def test_strip_html():
    assert feeds.strip_html("<p>a &amp; b</p><script>x</script><p>c</p>") == "a & b\nc"


def test_outlier_math():
    # channel: 1,000,000 views over 100 videos = 10k avg; a 100k video is a 10x outlier
    assert discover.outlier_score(100_000, 1_000_000, 100) == 10.0
    assert discover.outlier_score(5, 0, 0) is None
    assert discover.iso_seconds("PT1H2M3S") == 3723 and discover.iso_seconds("PT45S") == 45


def test_quality_schema_is_strict():
    import quality
    assert quality.SCHEMA["additionalProperties"] is False
    assert set(quality.SCHEMA["required"]) == set(quality.SCHEMA["properties"])


if __name__ == "__main__":
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f(); print("ok", f.__name__)
