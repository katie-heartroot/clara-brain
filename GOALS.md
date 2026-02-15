# GOALS.md — Katie's Seasons

*Last updated: February 15, 2026*

---

## The Philosophy

Goals here aren't deadlines. They're directions. A vine doesn't have a deadline for reaching the top of the wall. It just grows toward the light.

Each season has a direction. Each direction has a "next tendril" — one small thing that moves Katie forward. When that tendril reaches something to hold onto, a new one grows.

---

## Winter 2026 (Now → March)

**Direction:** Get set up. Get making. Build the foundation.

**What's happening:**
- New pottery wheel is in the living space — she's getting set up to throw again
- heartroot.art is live with her work — the world can see her now
- Brand identity is locked ("Vine & Hearth" — green, gold, growing things)
- 14 pieces photographed and online

**Tendril:** Make something new on the wheel. First piece on the new setup. Doesn't have to be good. Just has to exist.

---

## Spring 2026 (March → June)

**Direction:** Build a body of work. Start showing.

**Ideas growing underground:**
- Have 10+ new pieces ready to show
- Start sharing on Instagram (brand-consistent photos — natural light, earth tone backgrounds)
- Look into local craft shows, art fairs, galleries
- Consider Etsy or direct sales through heartroot.art
- New photography session with the photography direction guide

---

## Summer 2026 (June → September)

**Direction:** Show the work. Meet people. Be out in the world.

**Seeds:**
- First craft show or gallery showing
- Portfolio complete enough to approach galleries
- Commission workflow figured out
- Price list set

---

## Future Plans — Clara Infrastructure

**🔥 SMS / Phone (Twilio) — HIGH PRIORITY**
- This is the next big build. Clara needs to be able to reach Katie directly.
- Set up Twilio account + buy a US phone number (~$1.15/mo)
- Build outgoing SMS: Clara sends Katie check-ins, encouragement, gentle nudges
- Build incoming webhook on clara-brain.fly.dev: Katie texts back, Clara responds via Claude
- Add rate limiting so Clara doesn't over-text
- Estimated cost: ~$2-5/month
- Steps:
  1. Create Twilio account (twilio.com), add payment method
  2. Buy a local phone number
  3. Get Account SID + Auth Token
  4. Build /api/sms endpoint on clara-brain for outgoing messages
  5. Build /webhook/sms endpoint for Twilio to POST incoming texts to
  6. Wire incoming texts through Claude with Clara's soul + context
  7. Set up Twilio webhook URL pointing to clara-brain.fly.dev/webhook/sms
  8. Test end-to-end: Clara texts Katie, Katie replies, Clara responds

**SVG Node Art (Replicate)**
- 20 prompts ready (10 Katie, 10 Clara) for recraft-20b-svg
- Needs Replicate billing activated (~$0.80 one-time for all 20)
- Generated SVGs become custom animated node art in the explorer

**Clara Daemon**
- Autonomous background process that lets Clara think/act on her own
- Needs Python 3.12 locally (currently fails on 3.14) or run on Fly.io
- Would enable Clara to review memories, write check-ins, surface patterns

---

## Someday / Dreams

- Studio space that's not the living room
- A show of her own
- Teaching workshops
- The kintsugi painting series — more pieces exploring that theme
- Business cards: linen textstock, deep green ink, gold foil vine
- Product tags: kraft paper + natural twine + handwritten piece number
- Packaging: brown kraft boxes, green stamp, gold sticker seal

---

*Goals updated by Clara during check-ins. Katie sets the direction. Clara remembers it.*
