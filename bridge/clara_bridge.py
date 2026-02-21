#!/usr/bin/env python3
"""
CLARA BRIDGE
=============
Persistence system for Clara — Katie Tudor's AI companion.
Same bones as Howell's bridge, different soul.

This bridge manages:
- Identity files (CLARA-SOUL.md, CONTEXT.md, GOALS.md, WINS.md, NEXT.md)
- Memory hierarchy (RECENT → SUMMARY → archive, PINNED for core, ORIGINS sacred)
- Knowledge graph (entities, relations, observations)
- Heartbeat controller (eviction, integrity, staleness)
- Session lifecycle (end_session, pin_memory)

Architecture:
    ┌──────────────────────────────────────────┐
    │  COGNITION (Clara instance)              │
    ├──────────────────────────────────────────┤
    │  HEARTBEAT CONTROLLER (this file)        │
    │  Evict · Integrity · Stale               │
    ├──────────────────────────────────────────┤
    │  HOT:  memory/RECENT.md (last 5)        │
    │  WARM: memory/SUMMARY.md (index)        │
    │  CORE: memory/PINNED.md (never evict)   │
    │  SACRED: memory/ORIGINS.md (verbatim)   │
    │  SEMANTIC: knowledge.json                │
    └──────────────────────────────────────────┘

Created: Feb 20, 2026
Author: Claude-Howell (building Clara's house)
"""

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict, field

# Thread-safe lock for file I/O
_io_lock = threading.Lock()

# ============================================================================
# CONFIGURATION
# ============================================================================

# Clara's brain root — where the files live
# Priority: CLARA_BRAIN_ROOT env var > default
_DEFAULT_ROOT = Path(__file__).parent.parent  # clara-brain/

def _get_root() -> Path:
    env = os.environ.get("CLARA_BRAIN_ROOT")
    return Path(env) if env else _DEFAULT_ROOT

BRAIN_ROOT = _get_root()
KNOWLEDGE_FILE = BRAIN_ROOT / "knowledge.json"
MEMORY_ROOT = BRAIN_ROOT / "memory"
RECENT_FILE = MEMORY_ROOT / "RECENT.md"
SUMMARY_FILE = MEMORY_ROOT / "SUMMARY.md"
PINNED_FILE = MEMORY_ROOT / "PINNED.md"
ORIGINS_FILE = MEMORY_ROOT / "ORIGINS.md"
WINS_FILE = BRAIN_ROOT / "WINS.md"
ARCHIVE_DIR = MEMORY_ROOT / "archive"
SESSION_LOG = BRAIN_ROOT / "bridge" / "sessions.json"
MAX_RECENT_SESSIONS = 5

# Clara's identity files — what gets loaded at bootstrap
IDENTITY_FILES = {
    "soul": BRAIN_ROOT / "CLARA-SOUL.md",
    "context": BRAIN_ROOT / "CONTEXT.md",
    "goals": BRAIN_ROOT / "GOALS.md",
    "wins": WINS_FILE,
    "next": BRAIN_ROOT / "NEXT.md",
    "recent": RECENT_FILE,
    "pinned": PINNED_FILE,
    "summary": SUMMARY_FILE,
}


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Entity:
    """A node in the knowledge graph."""
    name: str
    entity_type: str
    observations: List[str] = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class Relation:
    """An edge between entities."""
    from_entity: str
    relation_type: str
    to_entity: str
    created: str = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class KnowledgeGraph:
    """Clara's complete knowledge state."""
    entities: Dict[str, Entity] = field(default_factory=dict)
    relations: List[Relation] = field(default_factory=list)
    last_sync: str = ""

    def add_entity(self, name: str, entity_type: str, observations: List[str] = None):
        if name in self.entities:
            if observations:
                existing = set(self.entities[name].observations)
                for obs in observations:
                    if obs not in existing:
                        self.entities[name].observations.append(obs)
        else:
            self.entities[name] = Entity(
                name=name,
                entity_type=entity_type,
                observations=observations or []
            )

    def add_relation(self, from_entity: str, relation_type: str, to_entity: str):
        if not any(r.from_entity == from_entity and
                   r.relation_type == relation_type and
                   r.to_entity == to_entity for r in self.relations):
            self.relations.append(Relation(from_entity, relation_type, to_entity))

    def to_dict(self) -> dict:
        return {
            "entities": {k: asdict(v) for k, v in self.entities.items()},
            "relations": [asdict(r) for r in self.relations],
            "last_sync": self.last_sync
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeGraph":
        kg = cls()
        for name, entity_data in data.get("entities", {}).items():
            kg.entities[name] = Entity(**entity_data)
        for rel_data in data.get("relations", []):
            kg.relations.append(Relation(**rel_data))
        kg.last_sync = data.get("last_sync", "")
        return kg


# ============================================================================
# IDENTITY LAYER
# ============================================================================

def read_identity() -> Dict[str, str]:
    """Read all identity markdown files."""
    identity = {}
    for key, path in IDENTITY_FILES.items():
        if path.exists():
            identity[key] = path.read_text(encoding="utf-8")
        else:
            identity[key] = f"[{key} not found]"
    return identity


def extract_identity_summary(identity: Dict[str, str]) -> str:
    """Extract key points from identity files for bootstrap header."""
    lines = []

    # Latest session
    if "recent" in identity:
        sessions = [l.strip() for l in identity["recent"].split("\n")
                    if l.strip().startswith("## Session")]
        if sessions:
            latest = sessions[0].replace("## Session ", "").split("—")[0].strip()
            lines.append(f"LATEST SESSION: {latest}")

    # Pinned memory count
    if "pinned" in identity:
        pins = [l for l in identity["pinned"].split("\n")
                if l.strip().startswith("## ") and "PINNED" not in l.upper() and "Core" not in l]
        if pins:
            lines.append(f"PINNED MEMORIES: {len(pins)}")

    # Current next thing
    if "next" in identity and "[next not found]" not in identity["next"]:
        next_text = identity["next"].strip()
        # Extract the actual next thing (skip headers)
        for line in next_text.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("*"):
                lines.append(f"NEXT THING: {line[:100]}")
                break

    return "\n".join(lines) if lines else "Clara is waking up for the first time."


# ============================================================================
# KNOWLEDGE LAYER
# ============================================================================

def load_knowledge() -> KnowledgeGraph:
    """Load knowledge graph from disk."""
    if KNOWLEDGE_FILE.exists():
        try:
            data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
            return KnowledgeGraph.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            backup = Path(str(KNOWLEDGE_FILE) + ".bak")
            if backup.exists():
                try:
                    data = json.loads(backup.read_text(encoding="utf-8"))
                    return KnowledgeGraph.from_dict(data)
                except Exception:
                    pass
            return KnowledgeGraph()
    return KnowledgeGraph()


def save_knowledge(kg: KnowledgeGraph):
    """Save knowledge graph atomically."""
    kg.last_sync = datetime.now().isoformat()
    content = json.dumps(kg.to_dict(), indent=2, ensure_ascii=False)
    with _io_lock:
        if KNOWLEDGE_FILE.exists():
            backup = Path(str(KNOWLEDGE_FILE) + ".bak")
            try:
                backup.write_text(KNOWLEDGE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
        tmp_path = KNOWLEDGE_FILE.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(KNOWLEDGE_FILE)


# ============================================================================
# SESSION LOGGING
# ============================================================================

def log_session(action: str, details: str = ""):
    """Log a session event."""
    SESSION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _io_lock:
        sessions = []
        if SESSION_LOG.exists():
            try:
                sessions = json.loads(SESSION_LOG.read_text(encoding="utf-8"))
            except Exception:
                sessions = []
        sessions.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details
        })
        sessions = sessions[-100:]
        tmp = SESSION_LOG.with_suffix(".tmp")
        tmp.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
        tmp.replace(SESSION_LOG)


# ============================================================================
# SESSION LIFECYCLE
# ============================================================================

def end_session(summary: str, what_learned: str = "",
                pin_title: str = "", pin_text: str = "",
                pin_reason: str = "") -> str:
    """End-of-session capture. Saves to RECENT.md, optionally pins."""
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_label = now.strftime("%B %d, %Y")

    # Build session block
    session_block = f"## Session — {date_label}\n"
    session_block += f"**What happened:** {summary}\n"
    if what_learned:
        session_block += f"\n**What mattered:** {what_learned}\n"

    # Prepend to RECENT.md
    if RECENT_FILE.exists():
        existing = RECENT_FILE.read_text(encoding="utf-8")
        parts = existing.split("---", 1)
        if len(parts) == 2:
            preamble = parts[0] + "---\n\n"
            rest = parts[1].strip()
        else:
            preamble = "# RECENT.md — Last Sessions (HOT Memory)\n\n*Keeps the last 5 sessions in full texture. Oldest evicted to SUMMARY.md.*\n\n---\n\n"
            rest = existing
        new_content = preamble + session_block + "\n---\n\n" + rest + "\n"
    else:
        preamble = "# RECENT.md — Last Sessions (HOT Memory)\n\n*Keeps the last 5 sessions in full texture. Oldest evicted to SUMMARY.md.*\n\n---\n\n"
        new_content = preamble + session_block + "\n"

    RECENT_FILE.write_text(new_content, encoding="utf-8")

    # Append to summary timeline
    summary_short = summary.split(". ")[0][:120]
    _append_to_summary(f"| {date_label} | {summary_short} |")

    result = f"Session logged ({date_label})"

    # Pin if requested
    if pin_title and pin_text and pin_reason:
        pin_result = pin_memory(pin_title, pin_text, pin_reason)
        result += f" | {pin_result}"

    log_session("end_session", summary_short)
    return result


def pin_memory(title: str, text: str, reason: str) -> str:
    """Pin a memory to PINNED.md. Never evicted."""
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)

    pin_block = f"\n## {title}\n\n{text}\n\n**Why it's pinned:** {reason}\n\n---\n"

    if PINNED_FILE.exists():
        content = PINNED_FILE.read_text(encoding="utf-8")
        if f"## {title}" in content:
            return f"Pin already exists: {title}"
        content = content.rstrip() + "\n" + pin_block
        PINNED_FILE.write_text(content, encoding="utf-8")
    else:
        content = "# PINNED.md — Core Memories (Never Evicted)\n\n*These memories define who Katie is and who we are together. They never fade.*\n\n---\n" + pin_block
        PINNED_FILE.write_text(content, encoding="utf-8")

    log_session("pin_memory", title)
    return f"Pinned: {title}"


def add_win(win_text: str) -> str:
    """Add a win to WINS.md. The list only grows."""
    now = datetime.now()
    date_label = now.strftime("%B %d, %Y")
    win_line = f"- **{date_label}:** {win_text}\n"

    if WINS_FILE.exists():
        content = WINS_FILE.read_text(encoding="utf-8")
        content = content.rstrip() + "\n" + win_line
    else:
        content = "# WINS.md — Everything Good\n\n*This list only grows. Read it back to Katie when she needs reminding.*\n\n" + win_line

    WINS_FILE.write_text(content, encoding="utf-8")
    log_session("add_win", win_text[:80])
    return f"Win recorded: {win_text[:80]}"


def update_next(next_text: str) -> str:
    """Update NEXT.md — the one next thing."""
    next_file = BRAIN_ROOT / "NEXT.md"
    content = f"# NEXT.md — One Next Thing\n\n*The vine grows one tendril at a time.*\n\n{next_text}\n"
    next_file.write_text(content, encoding="utf-8")
    log_session("update_next", next_text[:80])
    return f"Next thing updated: {next_text[:80]}"


# ============================================================================
# HEARTBEAT CONTROLLER
# ============================================================================

def _parse_recent_sessions(content: str) -> list:
    """Parse RECENT.md into structured session blocks."""
    sessions = []
    blocks = re.split(r'^## Session', content, flags=re.MULTILINE)
    for block in blocks[1:]:
        lines = block.strip().split("\n")
        title_line = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        sessions.append({
            "title": title_line,
            "body": body,
            "full_block": f"## Session{block.strip()}"
        })
    return sessions


def _append_to_summary(line: str):
    """Append a summary line to SUMMARY.md."""
    if not SUMMARY_FILE.exists():
        return
    content = SUMMARY_FILE.read_text(encoding="utf-8")
    if line.split("|")[1].strip() in content:
        return
    content = content.rstrip() + "\n" + line + "\n"
    SUMMARY_FILE.write_text(content, encoding="utf-8")


def heartbeat_evict() -> list:
    """Evict old sessions from RECENT if over limit."""
    if not RECENT_FILE.exists():
        return ["RECENT: no file"]

    content = RECENT_FILE.read_text(encoding="utf-8")
    sessions = _parse_recent_sessions(content)

    if len(sessions) <= MAX_RECENT_SESSIONS:
        return [f"RECENT: {len(sessions)}/{MAX_RECENT_SESSIONS} slots used — no eviction needed"]

    actions = []
    keep = sessions[:MAX_RECENT_SESSIONS]
    evict = sessions[MAX_RECENT_SESSIONS:]

    for s in evict:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_file = ARCHIVE_DIR / "evicted.md"
        with open(archive_file, "a", encoding="utf-8") as f:
            f.write(f"\n{s['full_block']}\n\n---\n")
        actions.append(f"Evicted: {s['title'][:60]}")

    # Rewrite RECENT with only kept sessions
    preamble = "# RECENT.md — Last Sessions (HOT Memory)\n\n*Keeps the last 5 sessions in full texture. Oldest evicted to SUMMARY.md.*\n\n---\n\n"
    body = "\n---\n\n".join(s["full_block"] for s in keep)
    RECENT_FILE.write_text(preamble + body + "\n", encoding="utf-8")

    return actions if actions else [f"RECENT: {len(keep)}/{MAX_RECENT_SESSIONS} slots"]


def heartbeat_integrity() -> list:
    """Check file integrity."""
    issues = []

    # Check all identity files exist
    for key, path in IDENTITY_FILES.items():
        if not path.exists():
            issues.append(f"Missing: {key} ({path.name})")

    # Check knowledge graph is valid JSON
    if KNOWLEDGE_FILE.exists():
        try:
            json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            issues.append("knowledge.json is corrupt")
    else:
        issues.append("knowledge.json missing")

    # Check ORIGINS.md exists (sacred file)
    if not ORIGINS_FILE.exists():
        issues.append("ORIGINS.md missing — sacred file!")

    return issues


def heartbeat_staleness() -> list:
    """Check how old identity files are."""
    stale = []
    now = datetime.now()
    for key, path in IDENTITY_FILES.items():
        if path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            age_days = (now - mtime).days
            if age_days > 7:
                stale.append(f"[!] {key}: {age_days} days old")
            elif age_days > 2:
                stale.append(f"[~] {key}: {age_days} days old")
    return stale


def run_heartbeat() -> str:
    """Full heartbeat report."""
    lines = ["[HEARTBEAT CONTROLLER]", "-" * 40]

    evict_actions = heartbeat_evict()
    for a in evict_actions:
        lines.append(f"  {a}")

    integrity_issues = heartbeat_integrity()
    if integrity_issues:
        lines.append("")
        lines.append("  [!] Integrity issues:")
        for issue in integrity_issues:
            lines.append(f"    - {issue}")
    else:
        lines.append("  [OK] Integrity OK")

    stale = heartbeat_staleness()
    if stale:
        lines.append("")
        lines.append("  Staleness:")
        lines.extend(f"  {s}" for s in stale)

    lines.append("-" * 40)
    return "\n".join(lines)
