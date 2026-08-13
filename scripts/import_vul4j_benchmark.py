"""Source-checkout wrapper for the packaged Vul4J importer CLI."""
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from codeevo.benchmark_cli import main  # noqa: E402


if __name__ == "__main__":
    main()
