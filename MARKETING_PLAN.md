# BetterFingers — Marketing Plan

*Flagship launch under **Source Arcanum**. First release; more apps to follow.*

---

## 1. The strategic frame

This launch has two jobs, not one:

1. **Get BetterFingers adopted** — real users, real installs, real word-of-mouth.
2. **Plant the Source Arcanum brand** — so the audience you build here carries over to the next app instead of starting from zero.

Everything below is designed so that when app #2 ships, you already have a Discord, a mailing list, a set of followers, and a reputation attached to *Source Arcanum* — not just to one tool. Treat BetterFingers as the front door to the studio.

---

## 2. Product snapshot

**What it is:** A free, fully-offline voice-to-text app that turns speech into clean, ready-to-use text in *any* application. Local Whisper handles transcription, a local LLM (Gemma via llama.cpp) cleans up / rephrases text through swappable "personas," and Kokoro TTS reads text back. Triggered by a global hotkey or a game controller.

**What makes it different (the moat):**

- **100% local.** No cloud, no account, no subscription, no telemetry. A built-in privacy dashboard *proves* nothing leaves the machine.
- **Free and open source** (MIT), by Donaven Crenshaw / Source Arcanum.
- **Built for gamers as a first-class use case** — controller binding, smart audio ducking, in-game chat integration, "review-first" or "auto-send" modes. Almost no competitor does this.
- **Smart, not just literal** — LLM personas (Formal, Polished, Unhinged, and more) clean up grammar, tone, and formatting on the fly.
- **Respects your hardware** — auto hardware detection + a model recommender that picks the right models for your tier (CPU-only through high-end GPU).

**Current limits to be honest about:** Windows + Linux only (no macOS yet); local LLM adds a real resource footprint on low-end machines (mitigated by the hardware-tier recommender); solo maintainer.

---

## 3. Positioning & messaging

**One-line positioning:**
> Local voice-to-text that types clean text into any app — private by design, free forever.

**Elevator pitch:**
> BetterFingers turns your voice into clean, ready-to-use text in any app — transcription, AI cleanup, and read-aloud, all running 100% on your own machine. No cloud, no subscription, no account. Free and open source. Use it while you game, write, or code — and if typing hurts, it gives your hands a rest.

**Four messaging pillars** (repeat these everywhere):

1. **Private by design** — it all runs locally; here's the dashboard that proves it.
2. **Free forever** — MIT-licensed, donation-supported, no paywall waiting to appear.
3. **Works everywhere you do** — any app, hotkey or controller, even mid-game.
4. **Smart, not literal** — AI personas clean up what you say instead of dumping raw dictation.

**Tagline options** (pick per audience):

- Privacy crowd: *"Your voice. Your machine. Nothing leaves."*
- Accessibility/RSI: *"Give your fingers a break."*
- Gamers: *"Talk to your team without alt-tabbing."*
- General: *"Talk. It types. Offline."*

---

## 4. Target audiences (ranked)

Don't market to "everyone" — lead with a wedge, then widen.

**1. Local-AI / privacy enthusiasts — best viral fit.**
Where they live: r/LocalLLaMA, r/selfhosted, r/privacy, Lemmy, Hacker News.
The hook: 100% local, MIT, no telemetry, privacy dashboard, model/hardware control.
Why first: this community *rewards* free offline tools with upvotes and evangelism, and they're the least skeptical of a solo dev.

**2. Gamers — your differentiator and reach engine.**
Where they live: game-specific subreddits/Discords, r/pcgaming, streamers/YouTubers.
The hook: talk to team chat hands-free without leaving the game; controller support; audio ducking.
Why: this is the scroll-stopping demo. Won't be your biggest donor base, but it's your most *shareable* angle.

**3. Accessibility / RSI / hands-free — strongest emotional pull + most likely donors.**
Where they live: r/accessibility, RSI and disability communities, ergonomics forums.
The hook: free hands-free typing that isn't a $200+ subscription; the name literally says it.
Why: these users get daily value and are the most likely to fund the project. Message with empathy; don't overclaim medical benefit.

**4. Writers / productivity — secondary, crowded.**
Where they live: r/productivity, note-taking and writing communities.
The hook: dictate clean drafts into any editor with AI cleanup.
Why: real but competitive (Wispr Flow, superwhisper, etc.). Use as a widening move, not the lead.

**Recommendation:** lead the *narrative* with privacy + accessibility (that's *why it exists*), and lead the *demos* with the gamer angle (that's *how it spreads*).

---

## 5. Source Arcanum — building the studio brand now

Because more apps are coming, spend a little effort here up front so it compounds:

- **Create a Source Arcanum home** — a simple GitHub org and a one-page site (Carrd, GitHub Pages, or itch.io publisher page) listing "Apps by Source Arcanum." BetterFingers is the first entry; leave room for the rest.
- **One Discord for the studio, not the app.** Channels per app, but the community is Source Arcanum's. This is the single most valuable asset you carry to app #2.
- **A "follow / notify me" capture** — a mailing list or the Discord's announcement channel — so you can tell existing fans about the next launch instead of re-acquiring an audience.
- **Consistent voice + identity** — a logo, a color, a one-line studio tagline (e.g., "Private, local-first tools that respect you"). Every BetterFingers touchpoint should quietly read *"by Source Arcanum."*
- **Credit the studio in-app** — the About screen and README both say "A Source Arcanum project."

The goal: by the time app #2 is announced, you post once in the existing Discord and mailing list and get instant traction.

---

## 6. Pre-launch checklist (the assets that actually move the needle)

- [ ] **A 15-second demo GIF** — voice → clean text landing in a real app. Goes at the top of the README and every post.
- [ ] **A 60–90s demo video** — one clip of everyday dictation, one clip of in-game chat. This is your best asset; over-invest here.
- [ ] **Marketing README** — hook line, GIF, feature highlights, screenshots, honest platform support, install steps, Sponsor section, "A Source Arcanum project."
- [ ] **Screenshots** — the dashboard, the privacy panel, persona picker.
- [ ] **Donation set up** — `.github/FUNDING.yml` (native Sponsor button) + Ko-fi, and consider itch.io pay-what-you-want (see §8).
- [ ] **Discord created** with basic channels + an issue/support flow.
- [ ] **Source Arcanum landing page** live.
- [ ] **Launch copy written** natively per platform (don't reuse one blurb).
- [ ] **A couple of early testers** who'll leave honest first comments/quotes on launch day.

---

## 7. Launch sequence

**Pre-launch (2–3 weeks out):** finish the checklist above, seed a handful of testers, and soft-post a "building this, feedback welcome" thread in one friendly community (r/LocalLLaMA) to warm up and collect fixes.

**Launch week — stagger, don't blast:**

1. **Day 1 — Show HN** ("Show HN: BetterFingers — 100% local voice-to-text with AI cleanup"). HN rewards candor: describe the architecture and the limitations openly.
2. **Day 1–2 — r/LocalLLaMA + r/selfhosted.** Most receptive audiences. Lead with "local, here's the privacy dashboard." Technical tone, no marketing speak.
3. **Day 2–3 — Product Hunt.** Crisp tagline, the GIF, respond to every comment fast.
4. **Day 3–4 — gaming communities.** Post the in-game clip where self-promo is allowed (game Discords, relevant subreddits — check each sub's rules first). Casual tone: "I built this so I can talk instead of alt-tabbing to type in chat."
5. **Day 4–5 — accessibility / RSI communities.** Empathetic framing, emphasize free + no subscription.
6. **Throughout — Lemmy cross-posts, an X/Bluesky thread, and submit to AlternativeTo + awesome-lists** (`whisper`, `local-llm`, `privacy`, `dictation`, `accessibility` topics on GitHub).

**Post-launch (first 2 weeks):** reply to *every* comment and issue; ship one visible fast-follow that addresses the top feedback (momentum signals a living project); reach out to 3–5 YouTubers/streamers who cover local AI or accessibility tools with a personal note and the demo.

---

## 8. Donation & sustainability

Your instinct — free with a donation button, nothing more — is correct, and it's also your competitive edge. The trust you earn from local + free is the whole moat; a nag popup would erode exactly the goodwill that makes people give.

**Setup:**

- **GitHub Sponsors** (recurring) — add `.github/FUNDING.yml` and GitHub renders a native "Sponsor" button on the repo.
- **Ko-fi or Buy Me a Coffee** (one-off tips).
- **itch.io (optional but strong)** — hosting the download as "pay-what-you-want / free" doubles as a donation channel *and* reaches the gamer audience natively.

**Framing:** *"Free forever. Donations fund model testing, hardware, and development."* One link in the README and the About screen. That's it — no in-app prompts.

**Low-effort goodwill perks** (optional): sponsors get their name in the credits and a Discord role. Costs nothing, drives recurring support.

---

## 9. Metrics that matter (for a free OSS tool)

- **Reach:** demo video views, HN/PH/Reddit upvotes, referral traffic to the repo.
- **Adoption:** GitHub stars, release download counts.
- **Community:** Discord members and weekly active chatters, mailing-list signups.
- **Support health:** open issues, median first-response time.
- **Sustainability:** number of sponsors + monthly recurring donations.

Rough first-90-days targets to sanity-check momentum (adjust to taste): a demo video with a few thousand views, 500–1,000+ GitHub stars, a Discord in the low hundreds, and your first recurring sponsors. The real win is a *retained* community you can talk to for app #2.

---

## 10. Risks & honest caveats

- **macOS gap** — the single biggest chunk of potential users is excluded. State it plainly in every launch post so Mac users don't feel misled; note it's on the roadmap only if you actually intend it (don't promise dates).
- **Solo-maintainer bandwidth** — a good launch brings a support wave. Set expectations, lean on the Discord + issue templates, and don't let launch week burn you out.
- **Resource footprint** — a local LLM is heavy on weak hardware. Message the hardware-tier recommender as the answer, and be upfront about minimum specs.
- **Reddit self-promo backlash** — several subs restrict promotion. Participate genuinely, follow each sub's rules, and never blast the same copy everywhere.

---

## 11. 30 / 60 / 90 snapshot

- **First 30 days:** ship the assets, launch across the staggered channels, respond relentlessly, and ship one fast-follow. Stand up the Source Arcanum home + Discord.
- **Days 30–60:** convert launch attention into a retained community — mailing list, regular Discord presence, get listed in awesome-lists/AlternativeTo, land 1–2 creator features.
- **Days 60–90:** publish a short "what's next" roadmap post (builds the Source Arcanum narrative), keep momentum with a feature update, and start warming the audience for app #2.

---

*Prepared for Source Arcanum · BetterFingers is Windows + Linux, MIT-licensed, free and offline.*
