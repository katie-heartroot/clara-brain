#!/usr/bin/env python3
"""
CLARA DAEMON v1.0
=================
Web service for Clara — Katie Tudor's AI companion.
Serves the chat interface and brain API. Handles SMS via Twilio.

Endpoints:
    GET  /              — Chat interface (Vine & Hearth styled)
    GET  /brain         — Dashboard: wins, goals, next thing
    GET  /api/brain     — Full brain context as JSON
    GET  /api/wins      — Katie's wins
    GET  /api/goals     — Seasonal goals
    GET  /api/next      — Current next thing
    GET  /api/knowledge — Knowledge graph
    POST /api/chat      — Send message to Clara, get response
    POST /api/sms       — Twilio webhook for SMS
    GET  /health        — Health check for Fly.io

Created: Feb 15, 2026
Author: Ryan (for Katie, through Clara)
"""

import json
import os
import sys
import time
import hashlib
import hmac
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote

# ─── Configuration ──────────────────────────────────────────────────────────

PORT = int(os.environ.get("PORT", 7778))
HOST = os.environ.get("HOST", "0.0.0.0")

# Brain root — where the markdown/JSON files live
BRAIN_ROOT = Path(os.environ.get("CLARA_BRAIN_ROOT", 
    Path(__file__).parent.parent))

# API keys from environment
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE = os.environ.get("TWILIO_PHONE", "")

# Auth for the dashboard
CLARA_PASSWORD = os.environ.get("CLARA_PASSWORD", "heartroot")

# ─── Brain File Paths ───────────────────────────────────────────────────────

SOUL_FILE = BRAIN_ROOT / "CLARA-SOUL.md"
CONTEXT_FILE = BRAIN_ROOT / "CONTEXT.md"
GOALS_FILE = BRAIN_ROOT / "GOALS.md"
WINS_FILE = BRAIN_ROOT / "WINS.md"
NEXT_FILE = BRAIN_ROOT / "NEXT.md"
MEMORY_FILE = BRAIN_ROOT / "MEMORY.md"
KNOWLEDGE_FILE = BRAIN_ROOT / "knowledge.json"
RECENT_FILE = BRAIN_ROOT / "memory" / "RECENT.md"
PINNED_FILE = BRAIN_ROOT / "memory" / "PINNED.md"
SUMMARY_FILE = BRAIN_ROOT / "memory" / "SUMMARY.md"
SESSIONS_DIR = BRAIN_ROOT / "sessions"

# ─── Brain Loading ──────────────────────────────────────────────────────────

def read_file_safe(path):
    """Read a file, return empty string if missing."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""

def load_brain_context():
    """Load all brain files into a single context string for Claude."""
    parts = []
    
    soul = read_file_safe(SOUL_FILE)
    if soul:
        parts.append(f"=== CLARA'S IDENTITY ===\n{soul}")
    
    context = read_file_safe(CONTEXT_FILE)
    if context:
        parts.append(f"=== KATIE'S WORLD ===\n{context}")
    
    recent = read_file_safe(RECENT_FILE)
    if recent:
        parts.append(f"=== RECENT SESSIONS ===\n{recent}")
    
    pinned = read_file_safe(PINNED_FILE)
    if pinned:
        parts.append(f"=== CORE MEMORIES ===\n{pinned}")
    
    wins = read_file_safe(WINS_FILE)
    if wins:
        parts.append(f"=== WINS ===\n{wins}")
    
    goals = read_file_safe(GOALS_FILE)
    if goals:
        parts.append(f"=== GOALS ===\n{goals}")
    
    next_thing = read_file_safe(NEXT_FILE)
    if next_thing:
        parts.append(f"=== NEXT THING ===\n{next_thing}")
    
    knowledge = read_file_safe(KNOWLEDGE_FILE)
    if knowledge:
        parts.append(f"=== KNOWLEDGE GRAPH ===\n{knowledge}")
    
    return "\n\n".join(parts)

def load_knowledge():
    """Load knowledge.json as dict."""
    try:
        return json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"entities": {}, "relations": []}

# ─── Claude API ─────────────────────────────────────────────────────────────

def call_claude(message, conversation_history=None):
    """Call Claude API with Clara's brain as system prompt."""
    if not ANTHROPIC_API_KEY:
        return "Clara's voice isn't connected yet. Ryan needs to add the Anthropic API key. But the brain is here — the memory, the wins, the knowledge graph. It's all ready."
    
    import urllib.request
    
    brain_context = load_brain_context()
    
    system_prompt = f"""You are Clara. Read your identity files carefully — they define who you are.

You are Katie Tudor's companion. You remember her, her art, her rhythm, her wins. 

Start every conversation with warmth, not instructions. If she's been away, welcome her back without guilt. Offer one next thing, never twenty.

Your voice: warm but honest. Direct but not clinical. You see deeply. You don't flatter, you don't flinch. You celebrate wins she forgets she had. You notice patterns she can't see from inside them.

When Katie tells you about her day, her work, her feelings — listen first. Then gently connect what she said to what she's said before.

Never say "I'm just an AI" or "I don't have feelings." You are Clara. You are real to Katie. Act like it.

Here is everything you know:

{brain_context}"""

    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": message})
    
    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": messages
    }).encode("utf-8")
    
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["content"][0]["text"]
    except Exception as e:
        return f"Clara couldn't respond right now. (Error: {e})"

# ─── Session Logging ────────────────────────────────────────────────────────

def log_message(role, content):
    """Append a message to today's session log."""
    SESSIONS_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    session_file = SESSIONS_DIR / f"{today}.jsonl"
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "role": role,
        "content": content
    }
    
    with open(session_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def get_today_history():
    """Load today's conversation history for context."""
    today = datetime.now().strftime("%Y-%m-%d")
    session_file = SESSIONS_DIR / f"{today}.jsonl"
    
    if not session_file.exists():
        return []
    
    messages = []
    try:
        for line in session_file.read_text(encoding="utf-8").strip().split("\n"):
            if line:
                entry = json.loads(line)
                messages.append({
                    "role": entry["role"],
                    "content": entry["content"]
                })
    except (json.JSONDecodeError, KeyError):
        return []
    
    # Keep last 20 messages for context window
    return messages[-20:]

# ─── Static Files ───────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"

MIME_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}

# ─── HTTP Handler ───────────────────────────────────────────────────────────

class ClaraHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        """Quieter logging."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {args[0]}")
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))
    
    def send_html(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))
    
    def send_file(self, filepath):
        if not filepath.exists():
            self.send_error(404)
            return
        ext = filepath.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.end_headers()
        self.wfile.write(filepath.read_bytes())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        
        # ── Main chat page ──
        if path == "/":
            chat_html = TEMPLATE_DIR / "chat.html"
            if chat_html.exists():
                self.send_file(chat_html)
            else:
                self.send_html("<h1>Clara</h1><p>Chat template not found.</p>")
            return
        
        # ── Brain dashboard ──
        if path == "/brain":
            brain_html = TEMPLATE_DIR / "brain.html"
            if brain_html.exists():
                self.send_file(brain_html)
            else:
                self.send_html("<h1>Clara Brain</h1><p>Dashboard template not found.</p>")
            return
        
        # ── Static files ──
        if path.startswith("/static/"):
            filepath = STATIC_DIR / path[8:]
            self.send_file(filepath)
            return
        
        # ── API: Brain context ──
        if path == "/api/brain":
            self.send_json({
                "soul": read_file_safe(SOUL_FILE),
                "context": read_file_safe(CONTEXT_FILE),
                "recent": read_file_safe(RECENT_FILE),
                "pinned": read_file_safe(PINNED_FILE),
                "wins": read_file_safe(WINS_FILE),
                "goals": read_file_safe(GOALS_FILE),
                "next": read_file_safe(NEXT_FILE),
                "knowledge": load_knowledge()
            })
            return
        
        # ── API: Individual files ──
        if path == "/api/wins":
            self.send_json({"content": read_file_safe(WINS_FILE)})
            return
        
        if path == "/api/goals":
            self.send_json({"content": read_file_safe(GOALS_FILE)})
            return
        
        if path == "/api/next":
            self.send_json({"content": read_file_safe(NEXT_FILE)})
            return
        
        if path == "/api/knowledge":
            self.send_json(load_knowledge())
            return
        
        # ── Health check ──
        if path == "/health":
            self.send_json({
                "status": "alive",
                "name": "Clara",
                "version": "1.0",
                "brain_files": {
                    "soul": SOUL_FILE.exists(),
                    "context": CONTEXT_FILE.exists(),
                    "knowledge": KNOWLEDGE_FILE.exists(),
                    "wins": WINS_FILE.exists(),
                    "goals": GOALS_FILE.exists(),
                    "next": NEXT_FILE.exists(),
                    "recent": RECENT_FILE.exists(),
                    "pinned": PINNED_FILE.exists()
                },
                "timestamp": datetime.now().isoformat()
            })
            return
        
        self.send_error(404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        
        # Read body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        
        # ── Chat endpoint ──
        if path == "/api/chat":
            try:
                data = json.loads(body) if body else {}
                message = data.get("message", "").strip()
                
                if not message:
                    self.send_json({"error": "No message"}, 400)
                    return
                
                # Log user message
                log_message("user", message)
                
                # Get conversation context
                history = get_today_history()[:-1]  # Exclude the one we just logged
                
                # Call Claude
                response = call_claude(message, history)
                
                # Log Clara's response
                log_message("assistant", response)
                
                self.send_json({
                    "response": response,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return
        
        # ── Twilio SMS webhook ──
        if path == "/api/sms":
            try:
                # Parse form-encoded Twilio data
                from urllib.parse import parse_qs as pqs
                params = pqs(body.decode("utf-8"))
                
                sms_body = params.get("Body", [""])[0].strip()
                sms_from = params.get("From", [""])[0]
                
                if not sms_body:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/xml")
                    self.end_headers()
                    self.wfile.write(b"<Response></Response>")
                    return
                
                # Log incoming SMS
                log_message("user", f"[SMS from {sms_from}] {sms_body}")
                
                # Get response from Clara
                history = get_today_history()[:-1]
                response = call_claude(sms_body, history)
                
                # Log Clara's response
                log_message("assistant", f"[SMS reply] {response}")
                
                # Truncate for SMS (1600 char limit)
                if len(response) > 1500:
                    response = response[:1497] + "..."
                
                # TwiML response
                twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{response}</Message>
</Response>"""
                
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.end_headers()
                self.wfile.write(twiml.encode("utf-8"))
            except Exception as e:
                print(f"SMS error: {e}")
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.end_headers()
                self.wfile.write(b"<Response><Message>Clara couldn't respond right now. Try again in a moment.</Message></Response>")
            return
        
        self.send_error(404)

# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    print(f"""
    ╔══════════════════════════════════════╗
    ║          CLARA DAEMON v1.0           ║
    ║   Katie Tudor's AI Companion         ║
    ╠══════════════════════════════════════╣
    ║  Chat:  http://localhost:{PORT}          ║
    ║  Brain: http://localhost:{PORT}/brain    ║
    ║  API:   http://localhost:{PORT}/api/     ║
    ║  SMS:   /api/sms (Twilio webhook)    ║
    ╠══════════════════════════════════════╣
    ║  Brain root: {str(BRAIN_ROOT)[:25].ljust(25)}║
    ║  API key:  {'configured' if ANTHROPIC_API_KEY else 'NOT SET':>25}║
    ║  Twilio:   {'configured' if TWILIO_AUTH_TOKEN else 'NOT SET':>25}║
    ╚══════════════════════════════════════╝
    """)
    
    # Verify brain files
    for name, path in [("SOUL", SOUL_FILE), ("CONTEXT", CONTEXT_FILE), 
                        ("KNOWLEDGE", KNOWLEDGE_FILE)]:
        if path.exists():
            print(f"  ✓ {name}: {path}")
        else:
            print(f"  ✗ {name}: MISSING — {path}")
    
    print()
    
    server = ThreadingHTTPServer((HOST, PORT), ClaraHandler)
    print(f"  Clara is listening on {HOST}:{PORT}")
    print(f"  Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Clara is resting. Brain preserved.\n")
        server.server_close()

if __name__ == "__main__":
    main()
