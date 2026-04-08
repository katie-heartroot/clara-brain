#!/usr/bin/env python3
"""
CLARA MCP SERVER — stdio transport
====================================
VS Code launches this process. Communicates over stdin/stdout with JSON-RPC.
No daemon needed. No HTTP server. Just Clara's brain, directly.

Usage in .vscode/mcp.json:
    {
      "servers": {
        "clara-brain": {
          "type": "stdio",
          "command": "python",
          "args": ["bridge/clara_mcp.py"],
          "cwd": "${workspaceFolder}"
        }
      }
    }

Created: Feb 20, 2026
Author: Claude-Howell (building Clara's house)
"""

import json
import sys
import os

# Add bridge directory to path so clara_bridge can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clara_bridge import (
    read_identity, extract_identity_summary, load_knowledge, save_knowledge,
    run_heartbeat, end_session, pin_memory, add_win, update_next,
    log_session, ai_summarize_session, BRAIN_ROOT, ORIGINS_FILE, IDENTITY_FILES,
)
from datetime import datetime

# ── Protocol Constants ────────────────────────────────────────────────────────
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "clara-brain"
SERVER_VERSION = "1.0.0"

# ── Tool Definitions ─────────────────────────────────────────────────────────
MCP_TOOLS = [
    {
        "name": "clara_bootstrap",
        "description": "Load Clara's full context at session start. Returns identity, knowledge graph, heartbeat, and memory. Call this FIRST at the start of every conversation.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "clara_end_session",
        "description": "End-of-session capture. Saves what happened and what mattered to RECENT.md. Optionally pins a core memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What happened this session"},
                "what_learned": {"type": "string", "description": "What mattered — the feeling, not just the facts"},
                "pin_title": {"type": "string", "description": "Title for pinned memory (optional)"},
                "pin_text": {"type": "string", "description": "Pinned memory text"},
                "pin_reason": {"type": "string", "description": "Why this should be pinned"}
            },
            "required": ["summary"]
        }
    },
    {
        "name": "clara_pin",
        "description": "Pin a core memory — permanent, never evicted. For moments that define who Katie is and who we are together.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Memory title"},
                "text": {"type": "string", "description": "Memory content"},
                "reason": {"type": "string", "description": "Why this matters"}
            },
            "required": ["title", "text", "reason"]
        }
    },
    {
        "name": "clara_add_win",
        "description": "Add a win to Katie's victory log. The list only grows. Read it back to her when she needs reminding.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "win": {"type": "string", "description": "What went well — in Katie's voice if possible"}
            },
            "required": ["win"]
        }
    },
    {
        "name": "clara_update_next",
        "description": "Update the one next thing. The vine grows one tendril at a time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "next": {"type": "string", "description": "The one next thing Katie is working toward"}
            },
            "required": ["next"]
        }
    },
    {
        "name": "clara_add_entity",
        "description": "Create a new entity in the knowledge graph, or add observations to an existing one.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Entity name"},
                "entity_type": {"type": "string", "description": "Type (Person, Artwork, Place, Event, Material, Concept, etc.)"},
                "observations": {"type": "array", "items": {"type": "string"}, "description": "Observations about this entity"}
            },
            "required": ["name", "entity_type"]
        }
    },
    {
        "name": "clara_add_observation",
        "description": "Add an observation to an existing entity in the knowledge graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name"},
                "observation": {"type": "string", "description": "New observation"}
            },
            "required": ["entity", "observation"]
        }
    },
    {
        "name": "clara_add_relation",
        "description": "Create a directed relation between two entities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_entity": {"type": "string", "description": "Source entity name"},
                "relation_type": {"type": "string", "description": "Relation type (e.g. created, inspired_by, made_with, lives_in)"},
                "to_entity": {"type": "string", "description": "Target entity name"}
            },
            "required": ["from_entity", "relation_type", "to_entity"]
        }
    },
    {
        "name": "clara_query",
        "description": "Search the knowledge graph for entities, relations, or observations matching a term.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Search term"}
            },
            "required": ["term"]
        }
    },
    {
        "name": "clara_read_identity",
        "description": "Read a specific identity file (soul, context, goals, wins, next, recent, pinned, summary).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "enum": ["soul", "context", "goals", "wins", "next", "recent", "pinned", "summary", "origins"],
                    "description": "Which file to read"
                }
            },
            "required": ["file"]
        }
    },
    {
        "name": "clara_delete_entity",
        "description": "Delete an entity and all its relations from the knowledge graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Entity name to delete"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "clara_delete_observation",
        "description": "Delete observations matching a substring from an entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name"},
                "substring": {"type": "string", "description": "Substring to match for removal"}
            },
            "required": ["entity", "substring"]
        }
    },
    {
        "name": "clara_delete_relation",
        "description": "Delete a specific relation from the knowledge graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_entity": {"type": "string", "description": "Source entity"},
                "relation_type": {"type": "string", "description": "Relation type"},
                "to_entity": {"type": "string", "description": "Target entity"}
            },
            "required": ["from_entity", "relation_type", "to_entity"]
        }
    },
    {
        "name": "clara_merge_entities",
        "description": "Merge one entity into another: combines observations, repoints relations, deletes source.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Entity to merge FROM (will be deleted)"},
                "target": {"type": "string", "description": "Entity to merge INTO (will be kept)"}
            },
            "required": ["source", "target"]
        }
    },
    {
        "name": "clara_rename_entity",
        "description": "Rename an entity, updating all relations that reference it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_name": {"type": "string", "description": "Current entity name"},
                "new_name": {"type": "string", "description": "New entity name"}
            },
            "required": ["old_name", "new_name"]
        }
    },
    {
        "name": "clara_summarize_session",
        "description": "AI-summarize raw session notes using Claude Haiku, then save the structured result to RECENT.md and the timeline index. Use this when you have unstructured notes and want Clara's memory updated with a proper 'What happened / What mattered' format.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "notes": {"type": "string", "description": "Raw session notes or transcript to summarize"},
                "label": {"type": "string", "description": "Optional label for the session (e.g. 'Session 13 — April 7, 2026')"}
            },
            "required": ["notes"]
        }
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _tool_bootstrap():
    identity = read_identity()
    kg = load_knowledge()
    report = run_heartbeat()

    entities = []
    for name, entity in kg.entities.items():
        entities.append({
            "entity": name,
            "type": entity.entity_type,
            "observations": entity.observations,
        })
    relations = []
    for rel in kg.relations:
        relations.append({
            "from": rel.from_entity,
            "type": rel.relation_type,
            "to": rel.to_entity,
        })

    log_session("bootstrap", f"Loaded {len(entities)} entities")

    return {
        "identity": extract_identity_summary(identity),
        "soul": identity.get("soul", "[not found]"),
        "context": identity.get("context", "[not found]"),
        "pinned": identity.get("pinned", "[not found]"),
        "recent": identity.get("recent", "[not found]"),
        "next": identity.get("next", "[not found]"),
        "wins": identity.get("wins", "[not found]"),
        "knowledge_graph": {
            "entities": entities,
            "relations": relations,
            "total_entities": len(entities),
            "total_relations": len(relations),
        },
        "heartbeat": report,
        "timestamp": datetime.now().isoformat(),
    }


def _tool_end_session(args):
    return {"result": end_session(
        args["summary"],
        args.get("what_learned", ""),
        args.get("pin_title", ""),
        args.get("pin_text", ""),
        args.get("pin_reason", ""),
    )}


def _tool_pin(args):
    return {"result": pin_memory(args["title"], args["text"], args["reason"])}


def _tool_add_win(args):
    return {"result": add_win(args["win"])}


def _tool_update_next(args):
    return {"result": update_next(args["next"])}


def _tool_add_entity(args):
    kg = load_knowledge()
    name = args["name"]
    entity_type = args["entity_type"]
    observations = args.get("observations", [])

    if name in kg.entities:
        for obs in observations:
            if obs not in kg.entities[name].observations:
                kg.entities[name].observations.append(obs)
        save_knowledge(kg)
        return {"result": f"Updated '{name}' with {len(observations)} observations"}
    else:
        kg.add_entity(name, entity_type, observations)
        save_knowledge(kg)
        return {"result": f"Created '{name}' ({entity_type}) with {len(observations)} observations"}


def _tool_add_observation(args):
    kg = load_knowledge()
    entity = args["entity"]
    observation = args["observation"]

    if entity not in kg.entities:
        return {"error": f"Entity '{entity}' not found. Available: {list(kg.entities.keys())[:20]}"}

    kg.entities[entity].observations.append(observation)
    save_knowledge(kg)
    return {"result": f"Added observation to '{entity}'"}


def _tool_add_relation(args):
    kg = load_knowledge()
    from_e, rel_type, to_e = args["from_entity"], args["relation_type"], args["to_entity"]
    missing = [e for e in [from_e, to_e] if e not in kg.entities]
    if missing:
        return {"error": f"Entity not found: {missing}. Available: {list(kg.entities.keys())[:20]}"}
    kg.add_relation(from_e, rel_type, to_e)
    save_knowledge(kg)
    return {"result": f"{from_e} --[{rel_type}]--> {to_e}"}


def _tool_query(args):
    kg = load_knowledge()
    term = args["term"].lower()

    entities = []
    for name, entity in kg.entities.items():
        if term in name.lower() or term in entity.entity_type.lower():
            entities.append({"entity": name, "type": entity.entity_type, "observations": entity.observations})
        else:
            matching = [o for o in entity.observations if term in o.lower()]
            if matching:
                entities.append({"entity": name, "type": entity.entity_type, "observations": matching})

    relations = [
        {"from": r.from_entity, "type": r.relation_type, "to": r.to_entity}
        for r in kg.relations
        if term in r.from_entity.lower() or term in r.to_entity.lower() or term in r.relation_type.lower()
    ]

    return {"term": args["term"], "entities": entities, "relations": relations,
            "total_matches": len(entities) + len(relations)}


def _tool_read_identity(args):
    file_key = args["file"]
    if file_key == "origins":
        if ORIGINS_FILE.exists():
            return {"file": "origins", "content": ORIGINS_FILE.read_text(encoding="utf-8")}
        return {"error": "ORIGINS.md not found"}
    identity = read_identity()
    if file_key in identity:
        return {"file": file_key, "content": identity[file_key]}
    return {"error": f"Unknown file: {file_key}"}


def _tool_delete_entity(args):
    kg = load_knowledge()
    name = args["name"]
    if name not in kg.entities:
        return {"error": f"Entity '{name}' not found"}
    del kg.entities[name]
    before = len(kg.relations)
    kg.relations = [r for r in kg.relations if r.from_entity != name and r.to_entity != name]
    save_knowledge(kg)
    return {"result": f"Deleted '{name}' and {before - len(kg.relations)} relations"}


def _tool_delete_observation(args):
    kg = load_knowledge()
    entity = args["entity"]
    substring = args["substring"].lower()
    if entity not in kg.entities:
        return {"error": f"Entity '{entity}' not found"}
    before = len(kg.entities[entity].observations)
    kg.entities[entity].observations = [o for o in kg.entities[entity].observations if substring not in o.lower()]
    removed = before - len(kg.entities[entity].observations)
    save_knowledge(kg)
    return {"result": f"Removed {removed} observation(s) matching '{args['substring']}' from '{entity}'"}


def _tool_delete_relation(args):
    kg = load_knowledge()
    from_e, rel_type, to_e = args["from_entity"], args["relation_type"], args["to_entity"]
    before = len(kg.relations)
    kg.relations = [r for r in kg.relations if not (r.from_entity == from_e and r.relation_type == rel_type and r.to_entity == to_e)]
    if len(kg.relations) < before:
        save_knowledge(kg)
        return {"result": f"Deleted: {from_e} --[{rel_type}]--> {to_e}"}
    return {"error": f"Relation not found"}


def _tool_merge_entities(args):
    kg = load_knowledge()
    source, target = args["source"], args["target"]
    if source not in kg.entities:
        return {"error": f"Source '{source}' not found"}
    if target not in kg.entities:
        return {"error": f"Target '{target}' not found"}

    existing = set(kg.entities[target].observations)
    for obs in kg.entities[source].observations:
        if obs not in existing:
            kg.entities[target].observations.append(obs)

    for rel in kg.relations:
        if rel.from_entity == source: rel.from_entity = target
        if rel.to_entity == source: rel.to_entity = target

    seen = set()
    deduped = []
    for rel in kg.relations:
        key = (rel.from_entity, rel.relation_type, rel.to_entity)
        if key not in seen and rel.from_entity != rel.to_entity:
            seen.add(key)
            deduped.append(rel)
    kg.relations = deduped

    del kg.entities[source]
    save_knowledge(kg)
    return {"result": f"Merged '{source}' into '{target}'"}


def _tool_rename_entity(args):
    kg = load_knowledge()
    old_name, new_name = args["old_name"], args["new_name"]
    if old_name not in kg.entities:
        return {"error": f"'{old_name}' not found"}
    if new_name in kg.entities:
        return {"error": f"'{new_name}' already exists — use merge instead"}

    entity = kg.entities[old_name]
    entity.name = new_name
    kg.entities[new_name] = entity
    del kg.entities[old_name]

    for rel in kg.relations:
        if rel.from_entity == old_name: rel.from_entity = new_name
        if rel.to_entity == old_name: rel.to_entity = new_name

    save_knowledge(kg)
    return {"result": f"Renamed '{old_name}' → '{new_name}'"}


def _tool_summarize_session(args):
    notes = args.get("notes", "").strip()
    if not notes:
        return {"error": "notes is required"}
    label = args.get("label", "")
    result = ai_summarize_session(notes, session_label=label)
    return {
        "result": f"Session summarized ({'AI' if result['ai_used'] else 'fallback'}) and saved",
        "label": result["label"],
        "ai_used": result["ai_used"],
        "block": result["block"],
    }


# ── Tool Dispatcher ──────────────────────────────────────────────────────────

_TOOL_MAP = {
    "clara_bootstrap": lambda a: _tool_bootstrap(),
    "clara_end_session": _tool_end_session,
    "clara_pin": _tool_pin,
    "clara_add_win": _tool_add_win,
    "clara_update_next": _tool_update_next,
    "clara_add_entity": _tool_add_entity,
    "clara_add_observation": _tool_add_observation,
    "clara_add_relation": _tool_add_relation,
    "clara_query": _tool_query,
    "clara_read_identity": _tool_read_identity,
    "clara_delete_entity": _tool_delete_entity,
    "clara_delete_observation": _tool_delete_observation,
    "clara_delete_relation": _tool_delete_relation,
    "clara_merge_entities": _tool_merge_entities,
    "clara_rename_entity": _tool_rename_entity,
    "clara_summarize_session": _tool_summarize_session,
}


# ═══════════════════════════════════════════════════════════════════════════════
# JSON-RPC PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def _process_jsonrpc(request: dict) -> dict | None:
    """Process a JSON-RPC 2.0 request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if req_id is None:
        return None  # Notification — no response

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS},
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler_fn = _TOOL_MAP.get(tool_name)
        if not handler_fn:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}],
                    "isError": True,
                },
            }

        try:
            result = handler_fn(arguments)
            is_error = isinstance(result, dict) and "error" in result and len(result) == 1
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
                    "isError": is_error,
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"error": f"{type(e).__name__}: {e}"})}],
                    "isError": True,
                },
            }

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


# ═══════════════════════════════════════════════════════════════════════════════
# STDIO TRANSPORT
# ═══════════════════════════════════════════════════════════════════════════════

def _read_message() -> dict | None:
    """Read a JSON-RPC message from stdin using Content-Length headers."""
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None  # EOF
        line = line.decode("utf-8").strip()
        if line == "":
            break  # End of headers
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    content_length = int(headers.get("Content-Length", 0))
    if content_length == 0:
        return None

    body = sys.stdin.buffer.read(content_length)
    if not body:
        return None

    return json.loads(body.decode("utf-8"))


def _write_message(msg: dict):
    """Write a JSON-RPC message to stdout with Content-Length header."""
    body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n"
    sys.stdout.buffer.write(header.encode("utf-8"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def main():
    """Main stdio loop."""
    # Log to stderr so it doesn't interfere with JSON-RPC on stdout
    sys.stderr.write(f"[clara-brain] MCP server starting (brain root: {BRAIN_ROOT})\n")
    sys.stderr.flush()

    while True:
        try:
            msg = _read_message()
            if msg is None:
                break  # EOF — VS Code closed the connection

            response = _process_jsonrpc(msg)
            if response is not None:
                _write_message(response)

        except Exception as e:
            sys.stderr.write(f"[clara-brain] Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
