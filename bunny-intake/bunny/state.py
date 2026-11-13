import json

from . import config


def load():
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text())
    return {"seen": {}, "yt_ids": {}, "pod_rss": {}}


def save(s):
    config.STATE_FILE.write_text(json.dumps(s, indent=2, sort_keys=True))
