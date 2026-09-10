"""Salesforce Case Finder — a local search UI over the BigQuery case archive."""

# One version, in `config`, because that is where the application already read
# it from to put it on the Settings page. Two statements rather than
# `import VERSION as __version__`: a renaming import is not a re-export, and
# ruff flags it as an unused import (F401).
from .config import VERSION

__version__ = VERSION
