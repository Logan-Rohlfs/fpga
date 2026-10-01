"""Local demo media for the GUI camera card's launch-synced demo mode. Toolkit-free.

Clips live in the ignored .sdr/media/ directory and are never tracked. Names are plain file names
(no directories) with a browser-playable video extension, so a request can never leave that directory.
"""
from pathlib import Path
import re

MEDIA_DIR = '.sdr/media'
NAME_MAX = 100
NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\.(?:mp4|m4v|webm)', re.IGNORECASE | re.ASCII)


def name_ok(name):
    """True for a plain clip file name of at most 100 characters ending in .mp4, .m4v or .webm."""
    return isinstance(name, str) and len(name) <= NAME_MAX and NAME_RE.fullmatch(name) is not None


def media_path(root, name):
    """Existing clip path under root/.sdr/media, or None. Raises ValueError on a bad name."""
    if not name_ok(name):
        raise ValueError('bad media name {!r}'.format(name))
    path = Path(root) / MEDIA_DIR / name
    return path if path.is_file() else None


def content_type(name):
    """Video media type for a clip name that passed name_ok."""
    return 'video/webm' if name.lower().endswith('.webm') else 'video/mp4'
