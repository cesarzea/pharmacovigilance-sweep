"""Turn the outputs of the latest subscription deployment into KEY=value lines (stdin -> stdout)."""

import json
import sys

outputs = json.load(sys.stdin) or {}
for key, item in outputs.items():
    print(f"{key.upper()}={item['value']}")
