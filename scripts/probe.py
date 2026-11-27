"""Temporary: run the real research fetch and show what it gets."""
import json, sys
sys.path.insert(0, "scripts")
import refresh
refresh.STATUS = {}
refresh.fetch_research()
d = json.load(open(refresh.DATA / "research.json"))
print("errors:", d["errors"])
from collections import Counter
print(Counter(i["source"] for i in d["items"]))
seen = set()
for i in d["items"]:
    if i["source"] in seen: continue
    seen.add(i["source"])
    print(f"\n{i['source']} | {i['published']} | {i['title']}\n  {i['link']}\n  summary: {i['summary'][:300]!r}")
