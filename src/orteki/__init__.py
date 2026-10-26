"""orteki: offline dictation and rewrite with recipes."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("orteki")
except PackageNotFoundError:  # running from source without installed metadata
    __version__ = "0+unknown"
