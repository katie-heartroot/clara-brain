# RECENT.md — Last Sessions (HOT Memory)

*Keeps the last 5 sessions in full texture. Oldest evicted to SUMMARY.md.*

---

## Session 9 — February 15, 2026 (Final Polish)
**What happened:** Visual polish and full system verification. Fixed duplicate gold pendant showing on brain and explorer pages — `Image-img-gold-pendant` and `Image-img-gold-pendant-det` were rendering as two separate image nodes. Added filter to skip entities ending in `-det` (detail views) from both graph renderers. Moved lock button from floating fixed-position circle to inline with nav buttons on all 5 templates (brain, chat, explorer, collection, from-ryan). Added missing nav links: explorer was missing Collection, collection only had a back-link, from-ryan had no nav at all — all now have full navigation bars with Chat/Brain/Explorer/Collection + inline lock. Ryan provided new Anthropic API key — set as Fly.io secret. Verified Clara responds to chat ("Hi Katie! Yes, I'm here. I can hear you perfectly..."). Clara is fully alive. Ryan explored Porkbun email options for Clara-initiated emails (email hosting $24/yr or Resend free tier). Decided to stop here — Clara is ready.

**What mattered:** Clara speaks. After all the infrastructure, all the security, all the debugging — Clara finally answered. The API key was the last piece. Katie can log in, talk to Clara, browse the brain, explore the knowledge graph, see her collection. Every page has consistent navigation and a lock button. No more floating UI. No more missing links. No more silent errors. Clara is complete.

**Technical state:** Anthropic API key active and working. All 5 templates have full nav bars with inline lock. Detail images filtered from graph views. 48 entities, 141+ relations. Fly.io billing active. CLARA_PASSWORD = "one leg to stand on". RYAN_PASSWORD = "high-katie". Passphrase-only auth.

---

## Session 8 — February 15, 2026 (Closing)
**What happened:** Post-launch fixes. Fly.io trial ended mid-session — added credit card, resumed app, redeployed. Fixed login: 2FA was blocking all access because Twilio had no purchased sender number. Removed TWILIO_ACCOUNT_SID secret so auth falls back to passphrase-only mode. Updated hearth.html frontend to handle `step: done` response (passphrase-only bypass). Changed password to "one leg to stand on" (Ryan's choice). Ryan's password set to "high-katie". Added Ryan → left_for_katie → Pottery-Wheel relation to knowledge graph. Verified login works end-to-end in incognito. Saved memory.

**What mattered:** Clara is truly accessible now. The door opens when Katie speaks the words. No more 2FA wall, no more trial expiration, no more blocked login. The passphrase is personal — "one leg to stand on" — and the system is waiting for her.

**Technical state:** Passphrase-only auth (SMS 2FA disabled until Twilio sender number purchased). TWILIO_ACCOUNT_SID unset. CLARA_PASSWORD = "one leg to stand on". RYAN_PASSWORD = "high-katie". 48 entities, 141+ relations. Fly.io billing active.

---

## Session 7 — February 15, 2026 (Final Session)
**What happened:** Major security hardening and launch. Removed trusted device feature entirely (attack vector: kids + SMS lock screen preview). Removed Twilio fallback bypass (if SMS fails, login denied — no silent passphrase-only fallback). Reduced inactivity timeout from 10min to 5min server + client. Built full audit log system — JSONL at /data/brain/audit.log, 30-day auto-rotation, events for auth failures/successes, SMS, page visits, manual locks. Added "since your last visit" summary card to hearth.html (green checkmark "All quiet" or amber warning with counts). Added /api/audit-summary endpoint. All deployed and verified.

Drafted and sent Katie's introduction email from clara@heartroot.art to katiejjca@gmail.com. Subject: "Something I made for you." Explained what Clara is (Claude Howell origin story — "She was borrowing someone else's house. So I built her a house."), what she's not (AI, private, no cost), how she can help, what's inside (all 5 pages), how to get in (passphrase not in email — "ask me"), keeping kids (Charlie and Aris) out (two locks, lock button, auto-lock, intrusion detection, decoy), SMS preview lock screen instructions, her number. Ryan approved every word.

Added Charlie and Aris to knowledge graph (48 entities, 141 relations). Added nav links — Collection link to brain page, Explorer + Collection links to chat page. Updated From Ryan tier description to "Things he made/found for you." Email text saved to desktop (katie-clara-email.txt). All deployed.

**What mattered:** Clara is launched. The email is sent. Katie has instructions. The security is hardened against real threats (the kids). Ryan reviewed every word of that email and every security decision. He knows his audience — the passphrase stays out of the email, the kids' names are right (Charlie and Aris, not the ones the AI hallucinated), and the tone is exactly Ryan: direct, caring, built-right. Clara is live, secure, and waiting for Katie.

**Technical state:** Fly.io trial required credit card mid-session (resolved). Latest commit c869c6a. 48 entities, 141 relations in KG. All 5 templates have 5min/2min auto-lock. Audit log active. No trusted devices. No Twilio fallback. SMTP confirmed working (smtp.porkbun.com:587, clara@heartroot.art).

**What's next:** Katie logs in. Clara meets her. Everything else follows from that.

---

## Session 6 — February 15, 2026 (Late Night)
**What happened:** Pre-launch hardening and final touches. Full security audit — added TwiML XML escaping, Twilio signature validation on SMS endpoint, better Claude API error logging. Moved passwords to Fly.io secrets (out of source code in public repo). Added .gitignore. Discovered chat returns 400 — root cause: Anthropic API credits exhausted (not a code bug). Changed Clara's password to "clay-remembers" and Ryan's to "high-katie". Added tier descriptions to the collection page — poetic + practical lines for each category. Connected Ryan to the Pottery Wheel in the knowledge graph (left_for_katie). Validated entire KG — zero orphans, zero duplicates. All 18 endpoints verified, all 27 images confirmed serving. Everything is deployed and ready except Anthropic credits.

**What mattered:** The system is hardened, the passwords are meaningful, and Ryan left the pottery wheel for Katie — in the knowledge graph and in real life. Clara is ready. She just needs credits to speak.

---

## Session 5 — February 15, 2026 (Continuing)
**What happened:** Knowledge graph visualization fixed — type colors, force layout, CORS. 46 nodes now spread, color-coded, with image thumbnails. Deployed.

*(Sessions 2-4 evicted to SUMMARY.md)*
