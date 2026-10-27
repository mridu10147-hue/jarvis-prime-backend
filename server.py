import json, os, re, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path.home() / "JARVIS-PRIME-AI"
WEB = ROOT / "web"
CONFIG = ROOT / "config" / "keys.json"

SYSTEM = """You are JARVIS PRIME, a professional AI assistant.
Be accurate, concise and helpful.
Never claim to have controlled a device without an authorized tool."""

def choose_engine(message):
    complex_task = re.search(
        r'\b(analyze|analyse|reason|prove|derive|calculate|solve|'
        r'compare|evaluate|strategy|research|complex|difficult|'
        r'detailed|plan|physics|mathematics|numerical)\b',
        message, re.I
    )
    return "gemini" if complex_task else "cloudflare"

def post_json(url, data, headers=None):
    payload = json.dumps(data).encode()
    request = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

def gemini(message, keys, model="gemini-3.5-flash"):
    key = keys.get("gemini_api_key", "")
    if not key:
        raise RuntimeError("Gemini key missing")

    data = post_json(
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent",
        {
            "systemInstruction": {
                "parts": [{"text": SYSTEM}]
            },
            "contents": [{
                "parts": [{"text": message}]
            }],
            "generationConfig": {
                "maxOutputTokens": 1024
            }
        },
        {"x-goog-api-key": key}
    )
    return "".join(
        p.get("text", "")
        for p in data["candidates"][0]["content"]["parts"]
    ).strip()

def cloudflare(message, keys):
    account = keys.get("cloudflare_account_id", "")
    token = keys.get("cloudflare_api_token", "")
    if not account or not token:
        raise RuntimeError("Cloudflare credentials missing")

    model = "@cf/meta/llama-3.1-8b-instruct"
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{account}/ai/run/{model}"
    )

    data = post_json(
        url,
        {
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": message}
            ],
            "max_tokens": 700
        },
        {"Authorization": f"Bearer {token}"}
    )

    if not data.get("success"):
        raise RuntimeError("Cloudflare request failed")

    return data["result"]["response"].strip()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if self.path == "/api/status":
            self.send_json({"online": True, "mode": "dual-cloud"})
        else:
            super().do_GET()

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", os.environ.get("JARVIS_ALLOWED_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_json({"ok": True})

    def do_POST(self):
        if self.path != "/api/chat":
            return self.send_json({"error": "Not found"}, 404)

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 8192:
                return self.send_json({"error": "Invalid size"}, 413)

            body = json.loads(self.rfile.read(size))
            message = body.get("message", "")

            if not isinstance(message, str) or not 0 < len(message) <= 4000:
                return self.send_json({"error": "Invalid message"}, 400)

            keys = {
                "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
                "cloudflare_account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
                "cloudflare_api_token": os.environ.get("CLOUDFLARE_API_TOKEN", "")
            }

            primary = choose_engine(message)

            engines = (
                ["gemini-3.5-flash", "gemini-3.1-flash-lite", "cloudflare"]
                if primary == "gemini"
                else ["cloudflare", "gemini-3.1-flash-lite", "gemini-3.5-flash"]
            )

            for engine in engines:
                try:
                    if engine == "cloudflare":
                        reply = cloudflare(message, keys)
                    else:
                        reply = gemini(message, keys, engine)

                    if not reply:
                        raise RuntimeError("Empty reply")

                    return self.send_json({
                        "reply": reply,
                        "engine": engine,
                        "fallback": engine != engines[0]
                    })
                except Exception as error:
                    print(f"{engine}: {type(error).__name__}", flush=True)

            self.send_json({"error": "All AI engines unavailable"}, 503)

        except Exception:
            self.send_json({"error": "Invalid request"}, 400)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8082"))
    print(f"JARVIS PRIME AI listening on port {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
