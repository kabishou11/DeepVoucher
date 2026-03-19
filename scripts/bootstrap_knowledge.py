from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from core.knowledge.parsers import bootstrap_knowledge


if __name__ == "__main__":
    result = bootstrap_knowledge(root)
    print(result)
