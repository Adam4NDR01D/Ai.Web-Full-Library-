"""Feed-cell parsing + resolving links to fetchable RSS URLs. No API keys needed here."""
import html
import json
import re

import requests

from . import config

LABELS = ("YouTube", "Podcast", "Substack")
_LINE = re.compile(r"^\s*(YouTube|Podcast|Substack)\s*:\s*(.+?)\s*$", re.I | re.M)
_URL = re.compile(r"https?://\S+")
_CHANNEL_ID = re.compile(r"(UC[\w-]{22})")


def format_cell(links: dict) -> str:
    """{'YouTube': 'https://..', 'Podcast': '..', 'Substack': '..'} -> multi-line cell text."""
    return "\n".join(f"{k}: {links[k]}" for k in LABELS if links.get(k))


def parse_cell(text: str) -> dict:
    """Inverse of format_cell. Each value may hold several URLs separated by ' | '."""
    out = {}
    for label, rest in _LINE.findall(text or ""):
        urls = _URL.findall(rest)
        if urls:
            out[label.capitalize() if label.lower() != "youtube" else "YouTube"] = urls
    return out


def _get(url, **kw):
    return requests.get(url, headers={"User-Agent": config.UA}, timeout=20, **kw)


# ---------- YouTube (no key: public RSS) ----------

def youtube_channel_id(url: str, cache: dict) -> str | None:
    """Resolve @handle / /c/ / /channel/ URL to a UC... id (cached in state)."""
    m = _CHANNEL_ID.search(url)
    if m and "/channel/" in url:
        return m.group(1)
    if url in cache:
        return cache[url]
    r = _get(url)
    r.raise_for_status()
    m = (re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', r.text)
         or re.search(r'"externalId":"(UC[\w-]{22})"', r.text)
         or re.search(r'"channelId":"(UC[\w-]{22})"', r.text))
    cid = m.group(1) if m else None
    cache[url] = cid
    return cid


def youtube_rss(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


# ---------- Podcasts (no key: iTunes lookup) ----------

def podcast_rss(url: str, cache: dict) -> str | None:
    """Apple Podcasts URL -> RSS via the free iTunes lookup API; RSS URLs pass through."""
    m = re.search(r"podcasts\.apple\.com/.*/id(\d+)", url)
    if not m:
        return url
    if url in cache:
        return cache[url]
    r = _get(f"https://itunes.apple.com/lookup?id={m.group(1)}&entity=podcast")
    r.raise_for_status()
    res = r.json().get("results", [])
    rss = res[0].get("feedUrl") if res else None
    cache[url] = rss
    return rss


def itunes_search(term: str, limit=5):
    r = _get("https://itunes.apple.com/search", params={"term": term, "media": "podcast", "limit": limit})
    r.raise_for_status()
    return [{"name": x.get("collectionName"), "artist": x.get("artistName"),
             "apple": x.get("collectionViewUrl"), "rss": x.get("feedUrl")} for x in r.json().get("results", [])]


# ---------- Substack / blogs ----------

def text_feed(url: str) -> str:
    """Substack or blog home URL -> RSS. Substack is always /feed; otherwise trust the URL
    if it already looks like a feed, else look for <link rel=alternate> on the page."""
    u = url.rstrip("/")
    if re.search(r"(/feed|/rss|\.xml|/atom[\w/.-]*)$", u):
        return url
    if "substack.com" in u or _looks_like_substack(u):
        return u + "/feed"
    try:
        r = _get(url)
        m = re.search(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', r.text)
        if m:
            return requests.compat.urljoin(url, html.unescape(m.group(1)))
    except requests.RequestException:
        pass
    return u + "/feed"


def _looks_like_substack(u):  # custom-domain Substacks still serve /feed; cheap default
    return False


def substack_search(query: str, limit=5):
    r = _get("https://substack.com/api/v1/publication/search",
             params={"query": query, "page": 0, "limit": limit})
    r.raise_for_status()
    data = r.json()
    pubs = data.get("publications") or data.get("results") or []
    out = []
    for p in pubs:
        sub = p.get("subdomain")
        url = p.get("custom_domain") and f"https://{p['custom_domain']}" or (sub and f"https://{sub}.substack.com")
        out.append({"name": p.get("name"), "author": p.get("author_name"), "url": url})
    return out


def youtube_search_channels(query: str, limit=5):
    """Scrape the public results page for channel hits (no key). Fragile by nature; used only
    as a suggestion source, never written to the sheet without review."""
    r = _get("https://www.youtube.com/results", params={"search_query": query, "sp": "EgIQAg%3D%3D"})
    r.raise_for_status()
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text)
    if not m:
        return []
    found = []
    for cr in re.finditer(r'"channelRenderer":\{"channelId":"(UC[\w-]{22})","title":\{"simpleText":"([^"]+)"', m.group(1)):
        found.append({"channel_id": cr.group(1), "title": json.loads(f'"{cr.group(2)}"'),
                      "url": f"https://www.youtube.com/channel/{cr.group(1)}"})
        if len(found) >= limit:
            break
    return found


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()
