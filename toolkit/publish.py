import sys
from pathlib import Path

# -I excludes consumer Python paths; only this action's packaged modules are trusted.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publication import main

if __name__ == "__main__":
    main()
