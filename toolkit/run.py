import sys
from pathlib import Path

# Isolated mode omits the script directory; trust only siblings of this pinned entrypoint.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from entrypoint import main

if __name__ == "__main__":
    main()
