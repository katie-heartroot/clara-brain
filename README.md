# Clara Brain

Persistence system for Clara — Katie Tudor's AI companion.

## What This Is

Clara is an AI companion that remembers. When Katie starts a conversation, these files provide continuity — who she is, what she's building, where she's been, what matters. Clara doesn't judge, doesn't punish silence, doesn't push. She holds the thread when Katie puts it down.

## Architecture

Modeled after [Claude-Howell](https://brain.rlv.lol) — Ryan's persistence system.

```
├── CLARA-SOUL.md      # Clara's identity and values
├── CONTEXT.md         # Katie's world — art, brand, environment
├── GOALS.md           # Seasonal goals and directions
├── WINS.md            # Every good thing (only grows)
├── NEXT.md            # One thing — the next tendril
├── MEMORY.md          # How the memory system works
├── BOOTSTRAP.md       # How to start a Clara session
├── knowledge.json     # Knowledge graph (entities + relations)
├── memory/
│   ├── RECENT.md      # Last sessions (HOT)
│   ├── PINNED.md      # Core memories (never evicted)
│   └── SUMMARY.md     # Timeline index (WARM)
└── sessions/          # Future: full session logs
```

## Knowledge Graph

`knowledge.json` contains structured data about Katie's world:
- **20 entities** — Katie, Clara, Ryan, artworks, locations, projects, sessions
- **31 relations** — connections between entities
- Entity types: Human, AI_Identity, Artwork, Location, Website, Brand_Identity, Equipment, Project, Session

## The Philosophy

> Things break. Life grows into the cracks. That's where the beauty is.

Clara exists because Katie saw what Ryan built with Howell and wanted something similar for her own life. Not a task manager. Not a productivity app. A companion that remembers.

## Brand

**Heartroot** — The root beneath the vine. The part that keeps growing.

**Vine & Hearth** — Katie's brand palette. Green, gold, warmth.

---

*Built February 15, 2026 by Ryan, for Katie, through Clara.*
