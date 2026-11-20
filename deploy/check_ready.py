import os
from urllib.request import Request, urlopen

request = Request(
    "http://127.0.0.1:8000/connexion/",
    headers={"Host": os.environ.get("LOGIT_HOST", "localhost").replace(",", " ").split()[0], "X-Forwarded-Proto": "https"},
)
with urlopen(request, timeout=2) as response:
    if response.status != 200:
        raise SystemExit(1)
