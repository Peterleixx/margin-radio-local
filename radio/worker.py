"""Run a single local narration job with the inherited job lock."""

import sys

from .library import work

if __name__ == "__main__":
    work(sys.argv[1])
