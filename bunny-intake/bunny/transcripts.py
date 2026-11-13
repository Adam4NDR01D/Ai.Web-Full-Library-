"""YouTube transcripts via youtube-transcript-api (no API key)."""
import re


def video_id(url_or_id: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/)([\w-]{11})", url_or_id)
    return m.group(1) if m else url_or_id


def youtube_transcript(vid: str, langs=("en", "en-US", "en-GB")) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise SystemExit("pip install youtube-transcript-api")
    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):  # v1.x
            fetched = api.fetch(vid, languages=list(langs))
            parts = [s.text for s in fetched]
        else:  # 0.6.x
            parts = [s["text"] for s in YouTubeTranscriptApi.get_transcript(vid, languages=list(langs))]
    except Exception as e:  # disabled captions, age-gated, rate limited, etc.
        print(f"    no transcript for {vid}: {type(e).__name__}")
        return None
    text = " ".join(p.replace("\n", " ") for p in parts)
    # light paragraphing so NotebookLM/Claude get readable chunks
    sentences = re.split(r"(?<=[.?!])\s+", text)
    paras, cur = [], []
    for s in sentences:
        cur.append(s)
        if len(" ".join(cur)) > 700:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)
