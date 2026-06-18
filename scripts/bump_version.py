import json
from datetime import datetime

with open("version.json") as f:
    v = json.load(f)

v["build"] += 1
v["build_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

with open("version.json", "w") as f:
    json.dump(v, f, indent=2)