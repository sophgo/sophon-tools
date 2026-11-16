import json
import sys

d = json.load(sys.stdin)
for m in d["models"]:
    print(m["id"], m["kind"], "ctx=%s" % m["context_length"],
          "fam=%r" % m.get("vector_family", "MISSING"), "loaded=%s" % m["loaded"])
