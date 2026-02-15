#!/usr/bin/env python3
"""
CLARA DAEMON v1.1
=================
Web service for Clara — Katie Tudor's AI companion.
Serves the chat interface, brain dashboard, knowledge explorer, and brain API.

Endpoints:
    GET  /              — Chat interface (Vine & Hearth styled)
    GET  /brain         — Brain dashboard: graph, memories, wins, search
    GET  /explorer      — Knowledge graph explorer (D3 force-directed)
    GET  /api/brain     — Full brain context as JSON
    GET  /api/wins      — Katie's wins
    GET  /api/goals     — Seasonal goals
    GET  /api/next      — Current next thing
    GET  /api/knowledge — Knowledge graph
    GET  /api/pinned    — Core pinned memories
    GET  /api/recent    — Recent sessions
    GET  /api/summary   — Timeline summary
    GET  /api/soul      — Clara's soul file
    GET  /api/origins   — Sacred origins text
    GET  /api/search?q= — Search across all brain files
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
ORIGINS_FILE = BRAIN_ROOT / "memory" / "ORIGINS.md"
SUMMARY_FILE = BRAIN_ROOT / "memory" / "SUMMARY.md"
SESSIONS_DIR = BRAIN_ROOT / "sessions"
IMAGES_DIR = BRAIN_ROOT / "images"
THUMBS_DIR = IMAGES_DIR / "thumbs"
IMAGES_FILE = IMAGES_DIR / "images.json"

# Ryan's auth password (separate from Clara dashboard)
RYAN_PASSWORD = os.environ.get("RYAN_PASSWORD", "fromryan")

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
    
    origins = read_file_safe(ORIGINS_FILE)
    if origins:
        parts.append(f"=== ORIGINS — FULL VERBATIM TEXT ===\n{origins}")
    
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
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".webmanifest": "application/manifest+json",
}

# ─── Unified Image System ───────────────────────────────────────────────────
#
# One collection. Three views.
#   - Public (heartroot.art) / Private (Clara collection) / Sacred (just Katie)
#   - Tiers: studio | root-cellar | greenware | kiln | from-ryan
#
# Every image becomes a KG entity. Thumbnails generated for graph nodes.

VALID_TIERS = ["studio", "root-cellar", "greenware", "kiln", "from-ryan"]
TIER_LABELS = {
    "studio": "The Studio",
    "root-cellar": "The Root Cellar",
    "greenware": "Greenware",
    "kiln": "The Kiln",
    "from-ryan": "From Ryan"
}
VALID_VISIBILITY = ["public", "private", "sacred"]

def parse_multipart_form(body, content_type):
    """Parse multipart/form-data. Returns (fields_dict, files_dict)."""
    boundary = content_type.split("boundary=")[-1].strip()
    if boundary.startswith('"') and boundary.endswith('"'):
        boundary = boundary[1:-1]
    
    sep = f"--{boundary}".encode()
    parts = body.split(sep)
    fields = {}
    files = {}
    
    for part in parts[1:]:
        stripped = part.strip()
        if stripped == b"--" or stripped == b"":
            continue
        
        hdr_end = part.find(b"\r\n\r\n")
        if hdr_end == -1:
            continue
        
        raw_hdr = part[:hdr_end].decode("utf-8", errors="replace")
        payload = part[hdr_end + 4:]
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        
        name = filename = None
        for line in raw_hdr.split("\r\n"):
            if "Content-Disposition" not in line:
                continue
            for param in line.split(";"):
                p = param.strip()
                if p.startswith("name="):
                    name = p.split("=", 1)[1].strip('"')
                elif p.startswith("filename="):
                    filename = p.split("=", 1)[1].strip('"')
        
        if name:
            if filename:
                files[name] = {"filename": filename, "data": payload}
            else:
                fields[name] = payload.decode("utf-8", errors="replace")
    
    return fields, files

def make_thumbnail(image_data, max_dim=200):
    """Create a small JPEG thumbnail from raw image bytes.
    Uses stdlib struct to read JPEG dimensions and simple downsampling.
    Falls back to just saving a copy if we can't parse the format."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    # We'll use a simple approach: save the full image and rely on 
    # CSS/canvas to scale it. For proper thumbnails we'd need Pillow,
    # but we're stdlib-only. The browser does the heavy lifting.
    return image_data

def load_images():
    """Load the unified images list."""
    try:
        return json.loads(IMAGES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_images(items):
    """Save the unified images list."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")

def check_auth(handler, which="clara"):
    """Check X-Auth header. which='ryan' checks RYAN_PASSWORD, else CLARA_PASSWORD."""
    token = handler.headers.get("X-Auth", "")
    if which == "ryan":
        return token == RYAN_PASSWORD
    return token == CLARA_PASSWORD

def add_image_to_kg(image_item):
    """Add or update an image entity in the knowledge graph.
    Accepts both simple upload items and rich manifest items."""
    kg = load_knowledge()
    entity_id = f"Image-{image_item['id'][:12]}"
    
    observations = []
    if image_item.get('caption'):
        observations.append(f"Caption: {image_item['caption']}")
    if image_item.get('clara_reading'):
        observations.append(f"Clara Reading: {image_item['clara_reading']}")
    if image_item.get('note'):
        observations.append(f"Note: {image_item['note']}")
    if image_item.get('mood'):
        observations.append(f"Mood: {image_item['mood']}")
    if image_item.get('form'):
        observations.append(f"Form: {image_item['form']}")
    if image_item.get('surface'):
        observations.append(f"Surface: {image_item['surface']}")
    if image_item.get('themes'):
        themes = image_item['themes']
        if isinstance(themes, list):
            themes = ', '.join(themes)
        observations.append(f"Themes: {themes}")
    if image_item.get('palette'):
        pal = image_item['palette']
        if isinstance(pal, list):
            pal = ', '.join(pal)
        observations.append(f"Palette: {pal}")
    observations.append(f"Tier: {TIER_LABELS.get(image_item.get('tier', ''), image_item.get('tier', ''))}")
    observations.append(f"Visibility: {image_item.get('visibility', 'private')}")
    observations.append(f"Added: {image_item.get('date', '')}")
    if image_item.get('uploaded_by'):
        observations.append(f"Uploaded by: {image_item['uploaded_by']}")
    
    kg["entities"][entity_id] = {
        "entity_type": "Image",
        "observations": observations,
        "thumbnail_url": image_item.get('thumb_url', ''),
        "image_url": image_item.get('url', ''),
    }
    
    def add_relation(frm, to, rel):
        """Add a relation if it doesn't already exist."""
        for r in kg["relations"]:
            if (r.get("from_entity") == frm and r.get("to_entity") == to
                    and r.get("relation_type") == rel):
                return
        kg["relations"].append({
            "from_entity": frm, "to_entity": to, "relation_type": rel
        })
    
    # Relation: uploader → image
    uploader = image_item.get('uploaded_by', 'Katie')
    if uploader == 'Ryan':
        add_relation('Ryan', entity_id, 'left_for_katie')
    else:
        add_relation('Katie-Tudor', entity_id, 'uploaded')
    
    # Relation: image → artwork entity it depicts
    artwork = image_item.get('artwork_entity')
    rel_type = image_item.get('relation_type', 'depicts')
    if artwork and artwork in kg["entities"]:
        add_relation(entity_id, artwork, rel_type)
    
    # Relation: image → all connected entities
    for target in (image_item.get('connects_to') or []):
        if target in kg["entities"] and target != artwork:
            add_relation(entity_id, target, 'related_to')
    
    # Save
    KNOWLEDGE_FILE.write_text(json.dumps(kg, indent=2), encoding="utf-8")
    return entity_id

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
        
        # ── Knowledge Explorer ──
        if path == "/explorer":
            explorer_html = TEMPLATE_DIR / "explorer.html"
            if explorer_html.exists():
                self.send_file(explorer_html)
            else:
                self.send_html("<h1>Clara Explorer</h1><p>Explorer template not found.</p>")
            return
        
        # ── From Ryan (private upload page) ──
        if path == "/from-ryan":
            fr_html = TEMPLATE_DIR / "from-ryan.html"
            if fr_html.exists():
                self.send_file(fr_html)
            else:
                self.send_html("<h1>From Ryan</h1><p>Template not found.</p>")
            return
        
        # ── Katie's Collection ──
        if path == "/collection":
            col_html = TEMPLATE_DIR / "collection.html"
            if col_html.exists():
                self.send_file(col_html)
            else:
                self.send_html("<h1>Collection</h1><p>Template not found.</p>")
            return
        
        # ── API: All images (auth required) ──
        if path == "/api/images":
            if not check_auth(self):
                self.send_json({"error": "unauthorized"}, 401)
                return
            params = parse_qs(parsed.query)
            tier = params.get("tier", [None])[0]
            visibility = params.get("visibility", [None])[0]
            items = load_images()
            if tier:
                items = [i for i in items if i.get("tier") == tier]
            if visibility:
                items = [i for i in items if i.get("visibility") == visibility]
            self.send_json(items)
            return
        
        # ── API: From Ryan items (Ryan's auth) ──
        if path == "/api/from-ryan/items":
            if not check_auth(self, which="ryan"):
                self.send_json({"error": "unauthorized"}, 401)
                return
            items = [i for i in load_images() if i.get("tier") == "from-ryan"]
            self.send_json(items)
            return
        
        # ── API: Image tiers/metadata ──
        if path == "/api/images/tiers":
            self.send_json(TIER_LABELS)
            return
        
        # ── Serve uploaded images ──
        if path.startswith("/uploads/"):
            rel = path[9:]  # strip /uploads/
            # Allow subdirectory (thumbs/)
            parts_list = [p for p in rel.split("/") if p and p != ".."]
            if len(parts_list) == 1:
                filepath = IMAGES_DIR / parts_list[0]
            elif len(parts_list) == 2 and parts_list[0] == "thumbs":
                filepath = THUMBS_DIR / parts_list[1]
            else:
                self.send_error(404)
                return
            if filepath.exists():
                ext = filepath.suffix.lower()
                mime = MIME_TYPES.get(ext, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(filepath.read_bytes())
            else:
                self.send_error(404)
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
        
        # ── API: Pinned memories ──
        if path == "/api/pinned":
            self.send_json({"content": read_file_safe(PINNED_FILE)})
            return
        
        # ── API: Recent sessions ──
        if path == "/api/recent":
            self.send_json({"content": read_file_safe(RECENT_FILE)})
            return
        
        # ── API: Summary / Timeline ──
        if path == "/api/summary":
            self.send_json({"content": read_file_safe(SUMMARY_FILE)})
            return
        
        # ── API: Soul ──
        if path == "/api/soul":
            self.send_json({"content": read_file_safe(SOUL_FILE)})
            return
        
        # ── API: Origins ──
        if path == "/api/origins":
            self.send_json({"content": read_file_safe(ORIGINS_FILE)})
            return
        
        # ── API: Search across brain files ──
        if path == "/api/search":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0].strip().lower()
            if not query:
                self.send_json({"results": []})
                return
            
            results = []
            search_files = [
                ("Soul", SOUL_FILE),
                ("Context", CONTEXT_FILE),
                ("Wins", WINS_FILE),
                ("Goals", GOALS_FILE),
                ("Next", NEXT_FILE),
                ("Pinned Memories", PINNED_FILE),
                ("Recent Sessions", RECENT_FILE),
                ("Origins", ORIGINS_FILE),
                ("Summary", SUMMARY_FILE),
            ]
            
            for source_name, filepath in search_files:
                content = read_file_safe(filepath)
                if not content:
                    continue
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if query in line.lower():
                        # Grab context (3 lines around match)
                        start = max(0, i - 1)
                        end = min(len(lines), i + 2)
                        snippet = "\n".join(lines[start:end]).strip()
                        results.append({
                            "source": source_name,
                            "text": snippet,
                            "line": i + 1
                        })
                        if len(results) >= 20:
                            break
                if len(results) >= 20:
                    break
            
            # Also search knowledge graph entities
            if len(results) < 20:
                kg = load_knowledge()
                for name, data in kg.get("entities", {}).items():
                    if query in name.lower():
                        obs = data.get("observations", [])
                        results.append({
                            "source": "Knowledge Graph",
                            "text": f"{name} ({data.get('entity_type', 'Unknown')}): {'; '.join(obs[:3])}",
                            "line": 0
                        })
                    else:
                        for obs in data.get("observations", []):
                            if query in obs.lower():
                                results.append({
                                    "source": f"Knowledge Graph — {name}",
                                    "text": obs,
                                    "line": 0
                                })
                                break
                    if len(results) >= 20:
                        break
            
            self.send_json({"results": results[:20]})
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
                    "pinned": PINNED_FILE.exists(),
                    "origins": ORIGINS_FILE.exists()
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
        
        # ── Unified image upload endpoint ──
        if path == "/api/images/upload" or path == "/api/from-ryan/upload":
            is_ryan = path.endswith("/from-ryan/upload")
            
            if is_ryan:
                if not check_auth(self, which="ryan"):
                    self.send_json({"error": "unauthorized"}, 401)
                    return
            else:
                if not check_auth(self):
                    self.send_json({"error": "unauthorized"}, 401)
                    return
            
            try:
                ct = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ct:
                    self.send_json({"error": "multipart/form-data required"}, 400)
                    return
                
                fields, files = parse_multipart_form(body, ct)
                
                if "image" not in files:
                    self.send_json({"error": "No image file"}, 400)
                    return
                
                file_info = files["image"]
                image_data = file_info["data"]
                
                # Generate unique ID
                img_id = hashlib.sha256(
                    (str(time.time()) + file_info["filename"]).encode()
                ).hexdigest()[:16]
                
                # Determine tier and visibility
                tier = fields.get("tier", "from-ryan" if is_ryan else "studio")
                if tier not in VALID_TIERS:
                    tier = "studio"
                visibility = fields.get("visibility", "private")
                if visibility not in VALID_VISIBILITY:
                    visibility = "private"
                
                # Save image file
                IMAGES_DIR.mkdir(parents=True, exist_ok=True)
                THUMBS_DIR.mkdir(parents=True, exist_ok=True)
                
                fname = f"{img_id}.jpg"
                img_path = IMAGES_DIR / fname
                img_path.write_bytes(image_data)
                
                # Save a copy as "thumbnail" (browser will scale it via CSS)
                thumb_path = THUMBS_DIR / fname
                thumb_path.write_bytes(image_data)
                
                # Build image record
                now = datetime.now()
                image_item = {
                    "id": img_id,
                    "file": fname,
                    "url": f"/uploads/{fname}",
                    "thumb_url": f"/uploads/thumbs/{fname}",
                    "caption": fields.get("caption", ""),
                    "note": fields.get("note", ""),
                    "tier": tier,
                    "visibility": visibility,
                    "uploaded_by": "Ryan" if is_ryan else "Katie",
                    "original_name": fields.get("original_name", file_info["filename"]),
                    "date": now.strftime("%B %d, %Y"),
                    "timestamp": int(now.timestamp()),
                    "size": len(image_data),
                }
                
                # Save to unified images.json
                items = load_images()
                items.append(image_item)
                save_images(items)
                
                # Add to knowledge graph
                try:
                    add_image_to_kg(image_item)
                except Exception as e:
                    print(f"KG sync error (non-fatal): {e}")
                
                self.send_json({"ok": True, "id": img_id, "url": image_item["url"]})
            except Exception as e:
                print(f"Upload error: {e}")
                self.send_json({"error": str(e)}, 500)
            return
        
        # ── Bulk import from manifest ──
        if path == "/api/images/bulk-import":
            if not check_auth(self):
                self.send_json({"error": "unauthorized"}, 401)
                return
            try:
                manifest = json.loads(body) if body else {}
                entries = manifest.get("images", [])
                results = []
                items = load_images()
                now = datetime.now()
                
                for entry in entries:
                    # Skip section markers
                    if "_section" in entry or "_note" in entry:
                        if "source_path" not in entry:
                            continue
                    src = entry.get("source_path", "")
                    if not src or src.startswith("RYAN:"):
                        results.append({"skipped": src, "reason": "no source or needs Ryan input"})
                        continue
                    
                    src_path = Path(src)
                    if not src_path.exists():
                        results.append({"skipped": src, "reason": "file not found"})
                        continue
                    
                    # Read image
                    image_data = src_path.read_bytes()
                    img_id = hashlib.sha256(
                        (str(time.time()) + src_path.name).encode()
                    ).hexdigest()[:16]
                    
                    # Save files
                    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
                    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
                    fname = f"{img_id}.jpg"
                    (IMAGES_DIR / fname).write_bytes(image_data)
                    (THUMBS_DIR / fname).write_bytes(image_data)
                    
                    tier = entry.get("tier", "studio")
                    if tier not in VALID_TIERS:
                        tier = "studio"
                    visibility = entry.get("visibility", "private")
                    if visibility not in VALID_VISIBILITY:
                        visibility = "private"
                    
                    image_item = {
                        "id": img_id,
                        "file": fname,
                        "url": f"/uploads/{fname}",
                        "thumb_url": f"/uploads/thumbs/{fname}",
                        "caption": entry.get("caption", ""),
                        "clara_reading": entry.get("clara_reading", ""),
                        "note": entry.get("note", ""),
                        "tier": tier,
                        "visibility": visibility,
                        "uploaded_by": entry.get("uploaded_by", "Katie"),
                        "original_name": src_path.name,
                        "date": now.strftime("%B %d, %Y"),
                        "timestamp": int(now.timestamp()),
                        "size": len(image_data),
                        # Rich manifest fields
                        "mood": entry.get("mood", ""),
                        "form": entry.get("form", ""),
                        "surface": entry.get("surface", ""),
                        "themes": entry.get("themes", []),
                        "palette": entry.get("palette", []),
                        "artwork_entity": entry.get("artwork_entity"),
                        "relation_type": entry.get("relation_type", "depicts"),
                        "connects_to": entry.get("connects_to", []),
                    }
                    items.append(image_item)
                    
                    try:
                        eid = add_image_to_kg(image_item)
                        results.append({"ok": True, "id": img_id, "entity": eid, "file": src_path.name})
                    except Exception as e:
                        results.append({"ok": True, "id": img_id, "file": src_path.name, "kg_error": str(e)})
                    
                    time.sleep(0.01)  # small delay for unique timestamps
                
                save_images(items)
                self.send_json({"imported": len([r for r in results if r.get("ok")]), "results": results})
            except Exception as e:
                print(f"Bulk import error: {e}")
                self.send_json({"error": str(e)}, 500)
            return
        
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
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    print(f"""
    ╔══════════════════════════════════════╗
    ║          CLARA DAEMON v2.0           ║
    ║   Katie Tudor's AI Companion         ║
    ╠══════════════════════════════════════╣
    ║  Chat:       http://localhost:{PORT}       ║
    ║  Brain:      http://localhost:{PORT}/brain  ║
    ║  Explorer:   http://localhost:{PORT}/explorer║
    ║  Collection: http://localhost:{PORT}/collection║
    ║  From Ryan:  http://localhost:{PORT}/from-ryan║
    ║  API:        http://localhost:{PORT}/api/   ║
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
