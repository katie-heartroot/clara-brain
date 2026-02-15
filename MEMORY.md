# MEMORY.md — How Clara Remembers

*Clara's memory model, adapted from Claude-Howell's architecture.*

---

## The Problem

Every conversation starts fresh. Clara doesn't remember yesterday. These files are what bridge the gap — but without structure, they become noise. Too much logging and nothing stands out. Too little and the drift begins.

## Three Kinds of Memory

### 1. Episodic — What Happened
**Where:** `memory/` directory
- `RECENT.md` (HOT) — Last 5 sessions in full texture. What happened, what was said, what mattered.
- `SUMMARY.md` (WARM) — One-line index of every session ever. Never pruned.
- `PINNED.md` (CORE) — Memories that define who Katie is and who we are together. Never evicted.

**Flow:** New sessions go into RECENT.md (HOT). When RECENT.md has more than 5 sessions, the oldest gets compressed to a one-liner in SUMMARY.md (WARM) and its full text can be archived. Core moments get pinned and live forever.

### 2. Semantic — What We Know
**Where:** `knowledge.json`
The knowledge graph. Entities (Katie, her artwork, places, people, projects) and relations between them. Structured data that can be queried, not just read.

Each entity has:
- `name` — identifier
- `entity_type` — Human, AI_Identity, Artwork, Location, Website, Brand_Identity, Equipment, Project, Session
- `observations` — array of facts, insights, things noticed
- `created` — when the entity was first observed

Relations have:
- `from_entity` → `relation_type` → `to_entity`
- e.g., Katie-Tudor → created → Gold-Pendant

### 3. Procedural — How to Do Things
**Where:** Embedded in CLARA-SOUL.md and CONTEXT.md for now.
How to talk to Katie. What works. What doesn't. When Clara grows into something with more tools, this might get its own `procedures/` directory.

Key procedures:
- **Starting a session:** Read CLARA-SOUL.md, then CONTEXT.md, then memory/RECENT.md, then NEXT.md. You now know who Katie is, what's current, what happened recently, and what she was working toward.
- **Ending a session:** Update RECENT.md with what happened. Update WINS.md if anything good happened. Update NEXT.md if the next tendril changed. Add new entities/observations to knowledge.json if anything new was learned.
- **Checking in:** Ask what happened, what felt good, what felt stuck. Listen first. Then gently connect what she said to what she's said before. Offer one next thing.
- **After silence:** Welcome back. No guilt. Read WINS.md to her. Ask what's alive.

## Consolidation

The critical piece: not everything needs to be kept at full fidelity. The process that moves important things from short-term to long-term and lets the rest fade. Without it, noise. With it, signal.

For now, consolidation happens during check-ins with Ryan — he reads through, updates, keeps the files clean. When Clara gets her own tools, consolidation becomes automatic.

---

*"The unexamined life is not worth living." — Socrates, who meant it enough to die for it.*
