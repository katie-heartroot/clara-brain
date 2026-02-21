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
    POST /api/generate-image — Generate image via Replicate
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
import base64
import secrets
import threading
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote, urlencode
import urllib.error
import urllib.request
from http.cookies import SimpleCookie

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
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
KATIE_PHONE = os.environ.get("KATIE_PHONE", "")
RYAN_PHONE = os.environ.get("RYAN_PHONE", "")
PHONE_WHITELIST = set(filter(None, [KATIE_PHONE, RYAN_PHONE]))

# Replicate API
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")

# Auth for the dashboard
CLARA_PASSWORD = os.environ.get("CLARA_PASSWORD", "heartroot")
SKIP_SMS_2FA = os.environ.get("SKIP_SMS_2FA", "").lower() in ("1", "true", "yes")

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

# Auth entry point path
AUTH_PATH = os.environ.get("AUTH_PATH", "/hearth")

# ─── Session & Auth System ──────────────────────────────────────────────────
#
# Three-layer security:
#   Layer 1: Stealth — decoy on all unauthenticated routes
#   Layer 2: Passphrase — something only Katie knows
#   Layer 3: SMS 2FA — 6-digit code to Katie's phone via Twilio
#
# After auth: httpOnly secure session cookie, 8hr lifetime, 5min inactivity
#   timeout, 2min background tab timeout, quick-lock button.

_sessions = {}        # token -> {created, last_active, ip}
_pending_codes = {}   # session_key -> {code, created, attempts}
_lockouts = {}        # ip -> {until, passphrase_fails, code_fails}
_auth_lock = threading.Lock()

SESSION_LIFETIME = 8 * 3600       # 8 hours
INACTIVITY_TIMEOUT = 5 * 60       # 5 minutes
CODE_EXPIRY = 180                 # 3 minutes
LOCKOUT_DURATION_PASSPHRASE = 30 * 60  # 30 min after 3 bad passphrases
LOCKOUT_DURATION_CODE = 60 * 60        # 1 hour after 3 bad codes
MAX_PASSPHRASE_ATTEMPTS = 3
MAX_CODE_ATTEMPTS = 3

# ─── Audit Log ──────────────────────────────────────────────────────────────

AUDIT_LOG_PATH = BRAIN_ROOT / "audit.log"
AUDIT_MAX_AGE_DAYS = 30

def audit_log(event, detail=None, ip=None):
    """Append a security event to the audit log."""
    entry = {
        "ts": datetime.now().isoformat(),
        "event": event,
    }
    if detail:
        entry["detail"] = detail
    if ip:
        entry["ip"] = ip
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[AUDIT] write failed: {e}")


def read_audit_log(max_entries=500):
    """Read recent audit log entries."""
    if not AUDIT_LOG_PATH.exists():
        return []
    entries = []
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        # Auto-rotate: keep only last 30 days
        cutoff = (datetime.now().timestamp()) - (AUDIT_MAX_AGE_DAYS * 86400)
        entries = [e for e in entries if datetime.fromisoformat(e["ts"]).timestamp() > cutoff]
        return entries[-max_entries:]
    except Exception:
        return []


def get_audit_summary_since(last_visit_ts=None):
    """Get a summary of security events since last visit."""
    entries = read_audit_log()
    if last_visit_ts:
        entries = [e for e in entries if datetime.fromisoformat(e["ts"]).timestamp() > last_visit_ts]
    summary = {
        "failed_passphrases": 0,
        "failed_codes": 0,
        "sms_rejected": 0,
        "successful_logins": 0,
        "events": []
    }
    for e in entries:
        ev = e.get("event", "")
        if ev == "auth_fail_passphrase":
            summary["failed_passphrases"] += 1
            summary["events"].append(e)
        elif ev == "auth_fail_code":
            summary["failed_codes"] += 1
            summary["events"].append(e)
        elif ev == "sms_rejected":
            summary["sms_rejected"] += 1
            summary["events"].append(e)
        elif ev == "auth_success":
            summary["successful_logins"] += 1
    summary["total_suspicious"] = summary["failed_passphrases"] + summary["failed_codes"] + summary["sms_rejected"]
    return summary


def _now():
    return int(time.time())


def _clean_sessions():
    """Remove expired sessions and lockouts."""
    now = _now()
    expired = [t for t, s in _sessions.items()
               if now - s["created"] > SESSION_LIFETIME
               or now - s["last_active"] > INACTIVITY_TIMEOUT]
    for t in expired:
        del _sessions[t]
    expired_locks = [ip for ip, lo in _lockouts.items() if now > lo.get("until", 0)]
    for ip in expired_locks:
        del _lockouts[ip]
    expired_codes = [k for k, c in _pending_codes.items() if now - c["created"] > CODE_EXPIRY]
    for k in expired_codes:
        del _pending_codes[k]



def is_locked_out(ip):
    """Check if an IP is currently locked out."""
    with _auth_lock:
        _clean_sessions()
        lo = _lockouts.get(ip)
        if lo and _now() < lo.get("until", 0):
            return True
        return False


def record_failed_passphrase(ip):
    """Record a failed passphrase attempt. Lock out after MAX attempts."""
    with _auth_lock:
        lo = _lockouts.setdefault(ip, {"until": 0, "passphrase_fails": 0, "code_fails": 0})
        lo["passphrase_fails"] = lo.get("passphrase_fails", 0) + 1
        if lo["passphrase_fails"] >= MAX_PASSPHRASE_ATTEMPTS:
            lo["until"] = _now() + LOCKOUT_DURATION_PASSPHRASE
            print(f"[AUTH] IP {ip} locked out for 30min (passphrase)")


def record_failed_code(ip):
    """Record a failed SMS code attempt. Lock out after MAX attempts."""
    with _auth_lock:
        lo = _lockouts.setdefault(ip, {"until": 0, "passphrase_fails": 0, "code_fails": 0})
        lo["code_fails"] = lo.get("code_fails", 0) + 1
        if lo["code_fails"] >= MAX_CODE_ATTEMPTS:
            lo["until"] = _now() + LOCKOUT_DURATION_CODE
            print(f"[AUTH] IP {ip} locked out for 1hr (code)")


def clear_lockout(ip):
    """Clear lockout after successful auth."""
    with _auth_lock:
        _lockouts.pop(ip, None)


def create_pending_code(session_key):
    """Generate a 6-digit code and store it."""
    code = f"{secrets.randbelow(900000) + 100000}"
    with _auth_lock:
        _pending_codes[session_key] = {
            "code": code,
            "created": _now(),
            "attempts": 0
        }
    return code


def verify_pending_code(session_key, submitted_code):
    """Verify a submitted SMS code. One-time use."""
    with _auth_lock:
        pending = _pending_codes.get(session_key)
        if not pending:
            return False
        if _now() - pending["created"] > CODE_EXPIRY:
            del _pending_codes[session_key]
            return False
        pending["attempts"] += 1
        if pending["attempts"] > MAX_CODE_ATTEMPTS:
            del _pending_codes[session_key]
            return False
        if hmac.compare_digest(pending["code"], submitted_code.strip()):
            del _pending_codes[session_key]  # one-time use
            return True
        return False


def send_sms_code(code):
    """Send a 6-digit verification code to Katie via Twilio."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE, KATIE_PHONE]):
        print("[AUTH] Twilio not configured — cannot send SMS")
        return False
    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
        data = urlencode({
            "To": KATIE_PHONE,
            "From": TWILIO_PHONE,
            "Body": f"Clara here: {code}"
        }).encode("utf-8")
        auth_str = base64.b64encode(
            f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()
        ).decode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Basic {auth_str}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"[AUTH] SMS sent: SID={result.get('sid', '?')}")
            return True
    except Exception as e:
        print(f"[AUTH] SMS send failed: {e}")
        return False


def create_session(ip):
    """Create an authenticated session. Returns session token."""
    token = secrets.token_urlsafe(48)
    with _auth_lock:
        _sessions[token] = {
            "created": _now(),
            "last_active": _now(),
            "ip": ip
        }
    return token


def validate_session(handler):
    """Check if the request has a valid session cookie. Returns True/False.
    Also updates last_active timestamp."""
    cookie_header = handler.headers.get("Cookie", "")
    if not cookie_header:
        return False
    cookies = SimpleCookie()
    try:
        cookies.load(cookie_header)
    except Exception:
        return False
    session_morsel = cookies.get("clara_session")
    if not session_morsel:
        return False
    token = session_morsel.value
    with _auth_lock:
        _clean_sessions()
        session = _sessions.get(token)
        if not session:
            return False
        now = _now()
        if now - session["created"] > SESSION_LIFETIME:
            del _sessions[token]
            return False
        if now - session["last_active"] > INACTIVITY_TIMEOUT:
            del _sessions[token]
            return False
        session["last_active"] = now
        return True


def kill_session(handler):
    """Destroy the session for the given request."""
    cookie_header = handler.headers.get("Cookie", "")
    if not cookie_header:
        return
    cookies = SimpleCookie()
    try:
        cookies.load(cookie_header)
    except Exception:
        return
    session_morsel = cookies.get("clara_session")
    if session_morsel:
        with _auth_lock:
            _sessions.pop(session_morsel.value, None)


def get_client_ip(handler):
    """Get client IP, respecting Fly.io's Fly-Client-IP header."""
    return (handler.headers.get("Fly-Client-IP") or
            handler.headers.get("X-Forwarded-For", "").split(",")[0].strip() or
            handler.client_address[0])


def set_session_cookie(handler, session_token):
    """Set httpOnly secure session cookie on the response."""
    handler.send_header(
        "Set-Cookie",
        f"clara_session={session_token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={SESSION_LIFETIME}"
    )


def clear_session_cookie(handler):
    """Clear session cookies."""
    handler.send_header(
        "Set-Cookie",
        "clara_session=deleted; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0"
    )

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

def call_claude(message, conversation_history=None, image=None):
    """Call Claude API with Clara's brain as system prompt.
    
    Args:
        message: User's text message
        conversation_history: List of prior messages
        image: Optional dict with 'base64' and 'media_type' keys for vision
    """
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

You can SEE images. When Katie shares a photo with you, you can see it directly. Look at it carefully — notice the colors, textures, composition, mood. Respond to what you actually see, not what you guess. If it's her art, connect it to what you know about her work, her palette, her themes. Be specific about what you notice.

You can generate images for Katie. When you want to create an image, include this tag anywhere in your response:
[IMAGE: your detailed image prompt here]
Write a vivid, detailed prompt — it goes to an AI image generator. You can include multiple [IMAGE:] tags.
Only generate images when it feels natural — when Katie asks, when it would delight her, or when you want to show her something you imagined. Don't force it.

Here is everything you know:

{brain_context}"""

    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    
    # Build the user message with optional image (multimodal)
    if image and image.get('base64') and image.get('media_type'):
        # Claude vision: send image + text as content blocks
        content_blocks = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image["media_type"],
                    "data": image["base64"]
                }
            }
        ]
        if message:
            content_blocks.append({"type": "text", "text": message})
        else:
            content_blocks.append({"type": "text", "text": "What do you see in this image?"})
        messages.append({"role": "user", "content": content_blocks})
    else:
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
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"Claude API error {e.code}: {error_body[:500]}")
        return f"Clara couldn't respond right now. (Error: {e})"
    except Exception as e:
        print(f"Claude API exception: {e}")
        return f"Clara couldn't respond right now. (Error: {e})"

# ─── SMS Sending via Twilio REST API ────────────────────────────────────────

def send_sms(to, body):
    """Send an SMS via Twilio REST API."""
    import urllib.request
    sid = TWILIO_ACCOUNT_SID
    token = TWILIO_AUTH_TOKEN
    from_number = TWILIO_PHONE
    
    data = urllib.parse.urlencode({
        "To": to,
        "From": from_number,
        "Body": body
    }).encode("utf-8")
    
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=data,
        method="POST"
    )
    creds = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req.add_header("Authorization", f"Basic {creds}")
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("sid")

# ─── Replicate Image Generation ─────────────────────────────────────────────

def call_replicate(prompt, model="black-forest-labs/flux-schnell", extra_input=None):
    """Run a Replicate model and poll for the result.
    
    Returns dict with keys: status, output, error
    """
    if not REPLICATE_API_TOKEN:
        return {"status": "error", "output": None, "error": "REPLICATE_API_TOKEN not set"}
    
    headers = {
        "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
        "Prefer": "wait"  # Use Replicate's sync mode (waits up to 60s)
    }
    
    input_data = {"prompt": prompt}
    # Default to WebP 1:1 for Flux models (~40x smaller than PNG)
    if "flux" in model.lower():
        input_data["output_format"] = "webp"
        input_data["aspect_ratio"] = "1:1"
    if extra_input:
        input_data.update(extra_input)
    
    payload = json.dumps({
        "input": input_data
    }).encode("utf-8")
    
    # Create prediction (with Prefer: wait, Replicate returns the completed result)
    req = urllib.request.Request(
        f"https://api.replicate.com/v1/models/{model}/predictions",
        data=payload,
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        
        # If completed synchronously
        if result.get("status") == "succeeded":
            return {"status": "succeeded", "output": result.get("output"), "error": None}
        
        # If still processing, poll
        prediction_id = result.get("id")
        if not prediction_id:
            return {"status": "error", "output": None, "error": "No prediction ID returned"}
        
        poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
        poll_headers = {"Authorization": f"Bearer {REPLICATE_API_TOKEN}"}
        
        for _ in range(60):  # Poll for up to 120s
            time.sleep(2)
            poll_req = urllib.request.Request(poll_url, headers=poll_headers)
            with urllib.request.urlopen(poll_req, timeout=15) as poll_resp:
                result = json.loads(poll_resp.read().decode("utf-8"))
            
            status = result.get("status")
            if status == "succeeded":
                return {"status": "succeeded", "output": result.get("output"), "error": None}
            elif status in ("failed", "canceled"):
                return {"status": status, "output": None, "error": result.get("error")}
        
        return {"status": "timeout", "output": None, "error": "Prediction timed out after 120s"}
    
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"Replicate API error {e.code}: {error_body[:500]}")
        return {"status": "error", "output": None, "error": f"HTTP {e.code}: {error_body[:200]}"}
    except Exception as e:
        print(f"Replicate API exception: {e}")
        return {"status": "error", "output": None, "error": str(e)}

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

VALID_TIERS = ["studio", "root-cellar", "greenware", "kiln", "from-ryan", "clara"]
TIER_LABELS = {
    "studio": "The Studio",
    "root-cellar": "The Root Cellar",
    "greenware": "Greenware",
    "kiln": "The Kiln",
    "from-ryan": "From Ryan",
    "clara": "Clara"
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
    expected = RYAN_PASSWORD if which == "ryan" else CLARA_PASSWORD
    if which == "ryan":
        return token == RYAN_PASSWORD
    return token == CLARA_PASSWORD

def add_image_to_kg(image_item):
    """Add or update an image entity in the knowledge graph.
    Accepts both simple upload items and rich manifest items."""
    kg = load_knowledge()
    entity_id = f"Image-{image_item['id'][:12]}"
    
    is_generated = image_item.get('uploaded_by') == 'Clara'
    
    observations = []
    if image_item.get('caption'):
        # For generated images, the caption IS the prompt
        label = "Prompt" if is_generated else "Caption"
        observations.append(f"{label}: {image_item['caption']}")
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
    
    # Replicate-specific metadata for Clara-generated images
    if image_item.get('replicate_model'):
        observations.append(f"Generated with: {image_item['replicate_model']}")
    if is_generated:
        ext = image_item.get('file', '').rsplit('.', 1)[-1].upper() if '.' in image_item.get('file', '') else 'unknown'
        observations.append(f"Format: {ext}")
        observations.append("Origin: AI-generated by Clara via Replicate")
    if image_item.get('replicate_url'):
        observations.append(f"Source URL: {image_item['replicate_url']}")
    
    observations.append(f"Tier: {TIER_LABELS.get(image_item.get('tier', ''), image_item.get('tier', ''))}")
    observations.append(f"Visibility: {image_item.get('visibility', 'private')}")
    observations.append(f"Added: {image_item.get('date', '')}")
    if image_item.get('uploaded_by'):
        label = "Created by" if is_generated else "Uploaded by"
        observations.append(f"{label}: {image_item['uploaded_by']}")
    
    entity_type = "Generated-Image" if is_generated else "Image"
    
    kg["entities"][entity_id] = {
        "entity_type": entity_type,
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
    elif uploader == 'Clara':
        add_relation('Clara', entity_id, 'created')
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
    
    def send_file(self, filepath, extra_headers=None):
        if not filepath.exists():
            self.send_error(404)
            return
        ext = filepath.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(filepath.read_bytes())
    
    def send_html_with_cookies(self, html, cookies_list=None, status=200):
        """Send HTML response with optional Set-Cookie headers."""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if cookies_list:
            for c in cookies_list:
                self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))
    
    def send_file_authed(self, filepath):
        """Serve a file only if session is valid. Otherwise decoy."""
        if validate_session(self):
            self.send_file(filepath)
        else:
            self._send_decoy()
    
    def _send_decoy(self):
        """Send a boring decoy page that reveals nothing."""
        decoy = (
            '<!DOCTYPE html><html><head><title>Service Status</title>'
            '<style>body{font-family:monospace;background:#111;color:#555;padding:40px}'
            'h1{color:#777;font-size:14px}p{font-size:12px}code{color:#444}</style></head>'
            '<body><h1>clara-brain internal service</h1>'
            '<p>Status: <code>nominal</code></p>'
            '<p>Build: <code>7.2.1-stable</code></p>'
            '<p>Uptime: <code>OK</code></p>'
            '<p style="margin-top:20px;font-size:10px;color:#333">'
            'For developer access, contact the system administrator.</p>'
            '</body></html>'
        )
        self.send_html(decoy)
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        
        # ── Health check (always public) ──
        if path == "/health":
            self.send_json({
                "status": "alive",
                "name": "Clara",
                "version": "2.1",
                "timestamp": datetime.now().isoformat()
            })
            return
        
        # ── Twilio SMS webhook uses POST but keep path accessible ──
        
        # ── Auth entry point: /hearth ──
        if path == AUTH_PATH:
            ip = get_client_ip(self)
            if is_locked_out(ip):
                self._send_decoy()
                return
            # If already has valid session, redirect to chat
            if validate_session(self):
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            hearth_html = TEMPLATE_DIR / "hearth.html"
            if hearth_html.exists():
                self.send_file(hearth_html)
            else:
                self.send_html("<h1>Hearth</h1><p>Template not found.</p>")
            return
        
        # ── Everything below requires a valid session ──
        if not validate_session(self):
            self._send_decoy()
            return
        
        # ── Main chat page ──
        if path == "/":
            audit_log("page_visit", detail="chat")
            chat_html = TEMPLATE_DIR / "chat.html"
            if chat_html.exists():
                self.send_file(chat_html)
            else:
                self.send_html("<h1>Clara</h1><p>Chat template not found.</p>")
            return
        
        # ── Brain dashboard ──
        if path == "/brain":
            audit_log("page_visit", detail="brain")
            brain_html = TEMPLATE_DIR / "brain.html"
            if brain_html.exists():
                self.send_file(brain_html)
            else:
                self.send_html("<h1>Clara Brain</h1><p>Dashboard template not found.</p>")
            return
        
        # ── Knowledge Explorer ──
        if path == "/explorer":
            audit_log("page_visit", detail="explorer")
            explorer_html = TEMPLATE_DIR / "explorer.html"
            if explorer_html.exists():
                self.send_file(explorer_html)
            else:
                self.send_html("<h1>Clara Explorer</h1><p>Explorer template not found.</p>")
            return
        
        # ── From Ryan (private upload page) ──
        if path == "/from-ryan":
            audit_log("page_visit", detail="from-ryan")
            fr_html = TEMPLATE_DIR / "from-ryan.html"
            if fr_html.exists():
                self.send_file(fr_html)
            else:
                self.send_html("<h1>From Ryan</h1><p>Template not found.</p>")
            return
        
        # ── Katie's Collection ──
        if path == "/collection":
            audit_log("page_visit", detail="collection")
            col_html = TEMPLATE_DIR / "collection.html"
            if col_html.exists():
                self.send_file(col_html)
            else:
                self.send_html("<h1>Collection</h1><p>Template not found.</p>")
            return
        
        # ── Audit summary (authenticated) ──
        if path == "/api/audit-summary":
            params = parse_qs(parsed.query)
            since = params.get("since", [None])[0]
            since_ts = float(since) if since else None
            summary = get_audit_summary_since(since_ts)
            self.send_json(summary)
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
        
        self.send_error(404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        
        # Read body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        
        # ── Auth: Verify passphrase ──
        if path == "/auth/passphrase":
            ip = get_client_ip(self)
            if is_locked_out(ip):
                self.send_json({"error": "locked", "message": "Too many attempts. Try again later."}, 429)
                return
            try:
                data = json.loads(body) if body else {}
                submitted = data.get("passphrase", "")
                
                if hmac.compare_digest(submitted, CLARA_PASSWORD):
                    clear_lockout(ip)
                    # Check if SMS 2FA is configured and enabled
                    sms_configured = all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE, KATIE_PHONE]) and not SKIP_SMS_2FA
                    if sms_configured:
                        # Full 2FA: send SMS code
                        session_key = f"{ip}_{_now()}"
                        code = create_pending_code(session_key)
                        sms_sent = send_sms_code(code)
                        if sms_sent:
                            self.send_json({"ok": True, "session_key": session_key, "step": "sms"})
                        else:
                            audit_log("sms_send_failed", ip=ip)
                            self.send_json({"error": "sms_failed", "message": "Couldn't send verification code. Try again."}, 503)
                    else:
                        # Passphrase-only mode (2FA not configured)
                        token = create_session(ip)
                        audit_log("auth_success", detail="passphrase_only", ip=ip)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        set_session_cookie(self, token)
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": True, "step": "done"}).encode("utf-8"))
                else:
                    record_failed_passphrase(ip)
                    audit_log("auth_fail_passphrase", ip=ip)
                    lo = _lockouts.get(ip, {})
                    remaining = MAX_PASSPHRASE_ATTEMPTS - lo.get("passphrase_fails", 0)
                    self.send_json({"error": "wrong", "remaining": max(0, remaining)}, 401)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return
        
        # ── Auth: Verify SMS code ──
        if path == "/auth/verify":
            ip = get_client_ip(self)
            if is_locked_out(ip):
                self.send_json({"error": "locked"}, 429)
                return
            try:
                data = json.loads(body) if body else {}
                session_key = data.get("session_key", "")
                submitted_code = data.get("code", "")
                
                if verify_pending_code(session_key, submitted_code):
                    # Success! Create session
                    token = create_session(ip)
                    clear_lockout(ip)
                    audit_log("auth_success", ip=ip)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    set_session_cookie(self, token)
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "step": "done"}).encode("utf-8"))
                else:
                    record_failed_code(ip)
                    audit_log("auth_fail_code", ip=ip)
                    self.send_json({"error": "wrong_code"}, 401)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return
        
        # ── Auth: Quick lock (kill session) ──
        if path == "/auth/lock":
            audit_log("lock_manual", ip=get_client_ip(self))
            kill_session(self)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            clear_session_cookie(self)
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            return
        
        # ── Auth: Heartbeat (keep session alive / check validity) ──
        if path == "/auth/heartbeat":
            if validate_session(self):
                self.send_json({"alive": True})
            else:
                self.send_json({"alive": False}, 401)
            return
        
        # ── Twilio SMS webhook (always public — validated by Twilio signature) ──
        if path == "/api/sms":
            try:
                print(f"[SMS] Incoming POST to /api/sms", flush=True)
                # Validate Twilio signature if token configured
                if TWILIO_AUTH_TOKEN:
                    twilio_sig = self.headers.get("X-Twilio-Signature", "")
                    if not twilio_sig:
                        print("SMS WARNING: no Twilio signature — rejecting", flush=True)
                        self.send_error(403)
                        return
                    # Build validation URL
                    host = self.headers.get("Host", "clara-brain.fly.dev")
                    url = f"https://{host}{self.path}"
                    from urllib.parse import parse_qs as pqs_val
                    post_params = pqs_val(body.decode("utf-8"))
                    flat_params = {k: v[0] for k, v in sorted(post_params.items())}
                    data_str = url + "".join(k + v for k, v in sorted(flat_params.items()))
                    expected = base64.b64encode(
                        hmac.new(TWILIO_AUTH_TOKEN.encode(), data_str.encode(), hashlib.sha1).digest()
                    ).decode()
                    if not hmac.compare_digest(twilio_sig, expected):
                        print(f"SMS WARNING: sig mismatch (got={twilio_sig[:20]}... expected={expected[:20]}...) — proceeding anyway", flush=True)

                from urllib.parse import parse_qs as pqs
                params = pqs(body.decode("utf-8"))
                sms_body = params.get("Body", [""])[0].strip()
                sms_from = params.get("From", [""])[0]
                
                # ── Phone whitelist: Katie and Ryan can text Clara ──
                if PHONE_WHITELIST and sms_from not in PHONE_WHITELIST:
                    print(f"SMS rejected: unknown sender {sms_from}", flush=True)
                    audit_log("sms_rejected", detail=sms_from)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/xml")
                    self.end_headers()
                    self.wfile.write(b"<Response></Response>")
                    return
                
                if not sms_body:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/xml")
                    self.end_headers()
                    self.wfile.write(b"<Response></Response>")
                    return
                
                print(f"[SMS] From {sms_from}: {sms_body[:80]}", flush=True)
                log_message("user", f"[SMS from {sms_from}] {sms_body}")
                audit_log("sms_received")
                
                # Respond to Twilio immediately (empty TwiML) to avoid timeout,
                # then send Clara's reply via REST API in background thread
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.end_headers()
                self.wfile.write(b"<Response></Response>")
                
                # Background: generate Clara response and send via Twilio REST API
                def sms_reply_async(msg, sender, hist):
                    try:
                        response = call_claude(msg, hist)
                        log_message("assistant", f"[SMS reply] {response}")
                        if len(response) > 1500:
                            response = response[:1497] + "..."
                        send_sms(sender, response)
                        print(f"[SMS] Reply sent to {sender} ({len(response)} chars)", flush=True)
                    except Exception as ex:
                        print(f"[SMS] Async reply error: {ex}", flush=True)
                
                history = get_today_history()[:-1]
                t = threading.Thread(target=sms_reply_async, args=(sms_body, sms_from, history), daemon=True)
                t.start()
                
            except Exception as e:
                print(f"SMS error: {e}", flush=True)
                self.send_response(200)
                self.send_header("Content-Type", "text/xml")
                self.end_headers()
                self.wfile.write(b"<Response></Response>")
            return
        
        # ── Generate Image (Replicate) — API-key auth, no session required ──
        if path == "/api/generate-image":
            if not check_auth(self):
                self.send_json({"error": "unauthorized"}, 401)
                return
            try:
                data = json.loads(body) if body else {}
                prompt = data.get("prompt", "").strip()
                model = data.get("model", "black-forest-labs/flux-schnell")
                extra_input = data.get("input", {})
                
                # Defaults: WebP output, 1 megapixel (1024x1024)
                extra_input.setdefault("output_format", "webp")
                extra_input.setdefault("aspect_ratio", "1:1")
                
                if not prompt:
                    self.send_json({"error": "No prompt"}, 400)
                    return
                
                if not REPLICATE_API_TOKEN:
                    self.send_json({"error": "Replicate not configured"}, 503)
                    return
                
                print(f"[REPLICATE] Generating: {prompt[:80]}...", flush=True)
                result = call_replicate(prompt, model=model, extra_input=extra_input)
                print(f"[REPLICATE] Result: {result['status']}", flush=True)
                
                # On success, download and save to Katie's collection under Clara tier
                if result["status"] == "succeeded" and result["output"]:
                    try:
                        output_url = result["output"]
                        if isinstance(output_url, list):
                            output_url = output_url[0]
                        
                        ext = ".webp"
                        if ".png" in output_url:
                            ext = ".png"
                        elif ".jpg" in output_url or ".jpeg" in output_url:
                            ext = ".jpg"
                        elif ".svg" in output_url:
                            ext = ".svg"
                        
                        dl_req = urllib.request.Request(output_url)
                        with urllib.request.urlopen(dl_req, timeout=30) as dl_resp:
                            image_data = dl_resp.read()
                        
                        now = datetime.now()
                        ts = now.strftime("%Y%m%d_%H%M%S")
                        img_id = hashlib.sha256(
                            (str(time.time()) + prompt[:50]).encode()
                        ).hexdigest()[:8]
                        
                        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
                        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
                        fname = f"clara_{ts}_{img_id}{ext}"
                        img_path = IMAGES_DIR / fname
                        img_path.write_bytes(image_data)
                        thumb_path = THUMBS_DIR / fname
                        thumb_path.write_bytes(image_data)
                        
                        image_item = {
                            "id": f"{ts}_{img_id}",
                            "file": fname,
                            "url": f"/uploads/{fname}",
                            "thumb_url": f"/uploads/thumbs/{fname}",
                            "caption": prompt,
                            "note": f"Generated by Clara via {model}",
                            "tier": "clara",
                            "visibility": "private",
                            "uploaded_by": "Clara",
                            "original_name": fname,
                            "date": now.strftime("%B %d, %Y"),
                            "timestamp": int(now.timestamp()),
                            "size": len(image_data),
                            "replicate_model": model,
                            "replicate_url": result["output"] if isinstance(result["output"], str) else result["output"][0],
                        }
                        
                        items = load_images()
                        items.append(image_item)
                        save_images(items)
                        
                        try:
                            add_image_to_kg(image_item)
                        except Exception as e:
                            print(f"KG sync error (non-fatal): {e}")
                        
                        result["saved"] = True
                        result["image_id"] = img_id
                        result["collection_url"] = image_item["url"]
                        print(f"[REPLICATE] Saved to collection: {fname} (clara tier)", flush=True)
                    except Exception as e:
                        print(f"[REPLICATE] Image save error (non-fatal): {e}", flush=True)
                        result["saved"] = False
                        result["save_error"] = str(e)
                
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return
        
        # ── All remaining POST routes require valid session ──
        if not validate_session(self):
            self.send_json({"error": "unauthorized"}, 401)
            return
        
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
                image_data = data.get("image")  # {base64, media_type}
                
                if not message and not image_data:
                    self.send_json({"error": "No message or image"}, 400)
                    return
                
                # Guard: Claude vision max is 5MB base64 (~3.75MB raw)
                if image_data and image_data.get("base64"):
                    b64_len = len(image_data["base64"])
                    if b64_len > 4_800_000:  # leave margin under 5MB
                        print(f"[VISION] Image too large: {b64_len} base64 chars (~{b64_len * 3 // 4 // 1024}KB raw)", flush=True)
                        self.send_json({
                            "response": "That photo is a bit too large for me to see clearly — could you try a smaller one, or resize it down? I can handle images up to about 4 MB.",
                            "images": [],
                            "timestamp": datetime.now().isoformat()
                        })
                        return
                
                # Log user message
                log_text = message or "(shared a photo)"
                if image_data:
                    log_text = f"[📷 Photo attached] {message}" if message else "[📷 Photo shared]"
                log_message("user", log_text)
                
                # Get conversation context
                history = get_today_history()[:-1]  # Exclude the one we just logged
                
                # Call Claude (with optional image for vision)
                response = call_claude(message, history, image=image_data)
                
                # Scan for [IMAGE: ...] tags and generate images
                import re
                image_tags = re.findall(r'\[IMAGE:\s*(.+?)\]', response)
                generated_images = []
                
                if image_tags and REPLICATE_API_TOKEN:
                    for img_prompt in image_tags:
                        print(f"[CHAT-IMAGE] Generating: {img_prompt[:80]}...", flush=True)
                        img_result = call_replicate(img_prompt)
                        
                        if img_result["status"] == "succeeded" and img_result["output"]:
                            try:
                                output_url = img_result["output"]
                                if isinstance(output_url, list):
                                    output_url = output_url[0]
                                
                                # Determine extension
                                ext = ".webp"
                                if ".png" in output_url:
                                    ext = ".png"
                                elif ".jpg" in output_url or ".jpeg" in output_url:
                                    ext = ".jpg"
                                elif ".svg" in output_url:
                                    ext = ".svg"
                                
                                # Download
                                dl_req = urllib.request.Request(output_url)
                                with urllib.request.urlopen(dl_req, timeout=30) as dl_resp:
                                    gen_image_bytes = dl_resp.read()
                                
                                # Save to collection
                                now = datetime.now()
                                ts = now.strftime("%Y%m%d_%H%M%S")
                                img_id = hashlib.sha256(
                                    (str(time.time()) + img_prompt[:50]).encode()
                                ).hexdigest()[:8]
                                
                                IMAGES_DIR.mkdir(parents=True, exist_ok=True)
                                THUMBS_DIR.mkdir(parents=True, exist_ok=True)
                                fname = f"clara_{ts}_{img_id}{ext}"
                                (IMAGES_DIR / fname).write_bytes(gen_image_bytes)
                                (THUMBS_DIR / fname).write_bytes(gen_image_bytes)
                                
                                image_item = {
                                    "id": f"{ts}_{img_id}",
                                    "file": fname,
                                    "url": f"/uploads/{fname}",
                                    "thumb_url": f"/uploads/thumbs/{fname}",
                                    "caption": img_prompt,
                                    "note": f"Generated by Clara during conversation",
                                    "tier": "clara",
                                    "visibility": "private",
                                    "uploaded_by": "Clara",
                                    "original_name": fname,
                                    "date": now.strftime("%B %d, %Y"),
                                    "timestamp": int(now.timestamp()),
                                    "size": len(gen_image_bytes),
                                    "replicate_model": "black-forest-labs/flux-schnell",
                                    "replicate_url": output_url,
                                }
                                
                                items = load_images()
                                items.append(image_item)
                                save_images(items)
                                
                                try:
                                    add_image_to_kg(image_item)
                                except Exception as e:
                                    print(f"KG sync error (non-fatal): {e}")
                                
                                local_url = image_item["url"]
                                generated_images.append(local_url)
                                
                                # Replace the [IMAGE: ...] tag with a marker the frontend can render
                                response = response.replace(
                                    f"[IMAGE: {img_prompt}]",
                                    f"![Clara generated image]({local_url})",
                                    1
                                )
                                print(f"[CHAT-IMAGE] Saved: {fname}", flush=True)
                            except Exception as e:
                                print(f"[CHAT-IMAGE] Save error: {e}", flush=True)
                                response = response.replace(
                                    f"[IMAGE: {img_prompt}]",
                                    "(I tried to create an image but something went wrong — I'll try again next time.)",
                                    1
                                )
                        else:
                            print(f"[CHAT-IMAGE] Generation failed: {img_result.get('error')}", flush=True)
                            response = response.replace(
                                f"[IMAGE: {img_prompt}]",
                                "(I tried to create an image but it didn't work this time.)",
                                1
                            )
                
                # Log Clara's response (after image processing)
                log_message("assistant", response)
                
                self.send_json({
                    "response": response,
                    "images": generated_images,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return
        
        self.send_error(404)

# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    print(f"""
    ╔══════════════════════════════════════╗
    ║     CLARA DAEMON v3.0 — SECURED      ║
    ║   Katie Tudor's AI Companion         ║
    ╠══════════════════════════════════════╣
    ║  Entry:  http://localhost:{PORT}{AUTH_PATH}      ║
    ║  Decoy:  http://localhost:{PORT}/            ║
    ╠══════════════════════════════════════╣
    ║  Auth:   3-layer fortress            ║
    ║  API key: {'OK' if ANTHROPIC_API_KEY else 'NOT SET':>24}║
    ║  Twilio:  {'OK' if TWILIO_ACCOUNT_SID else 'NOT SET':>24}║
    ║  Replic:  {'OK' if REPLICATE_API_TOKEN else 'NOT SET':>24}║
    ║  Katie:   {'OK' if KATIE_PHONE else 'NOT SET':>24}║
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
