# Clara Brain — Plan

Persistence system for Clara — Katie Tudor's AI companion. Memory, sessions, and personality continuity.

## Stack
Python, JSON file storage. FastHTTP daemon. Anthropic Haiku for summarization.

## Current State (April 7, 2026 — commit b87c1c8)

- Built: app/, memory/, sessions/ structure
- Memory persistence working
- 16 MCP tools in bridge/clara_mcp.py
- `clara_summarize_session` — AI (Haiku) → raw notes → structured RECENT.md block
- `_append_to_summary` fixed — proper 3-col SUMMARY.md rows
- `heartbeat_evict` — now updates SUMMARY.md on eviction (no more silent drops)
- Fly.io: suspended (needs resume + redeploy)

## Roadmap

- [x] Long-term memory consolidation (heartbeat_evict → SUMMARY.md)
- [x] Session summarization (clara_summarize_session MCP tool)
- [ ] Fly.io resume + redeploy with latest code
- [ ] Auto-run heartbeat on bootstrap
- [ ] SMS Twilio toll-free A2P 10DLC verification (unblocks outbound)
- [ ] Deploy consideration — if Katie needs remote access (iPad)
