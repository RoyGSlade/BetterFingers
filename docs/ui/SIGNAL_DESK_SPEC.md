# BetterFingers — "Signal Desk" UI Spec (director-authored from mockups)

Source mockups (studied pixel-by-pixel by the director):
`01_talk_workspace.png`, `02_library_workspace.png`, `03_studio_workspace.png`, `04_overlay_review_deck.png`.

This is the source of truth for the redesign. Workers implement to THIS; the
director verifies rendered fidelity by screenshot. **No existing feature may be
dropped** — every control in `CURRENT_UI_INVENTORY.md` must land somewhere in
this new structure (mapping in §8).

---

## 1. Brand & naming
- Product wordmark: **BetterFingers** (light weight) with **SIGNAL DESK** kicker beneath (small, letter-spaced, muted).
- The engine/overlay identity is **SIGNAL CORE** (the circular audio ring is the "Signal Core").
- Top-right of every main workspace shows a context pill: `Signal Core ●` (Talk/Library) or `Persona Foundry ●` (Studio) — green dot = engine live.
- App version chip bottom-left of nav rail: avatar + "BetterFingers v1.2.0".

## 2. Design tokens

### Color (dark theme is primary; hexes are director's calibrated targets)
- Background base: `#0A0E14` (near-black, faint blue). App gradient: top `#0B1017` → bottom `#080B10`.
- Surface / card: `#0F151D`; raised card: `#131A23`; inset (transcript boxes): `#0C1219`.
- Border / hairline: `#1C2733` (default), `#26333F` (hover).
- Text: primary `#E8EEF4`, secondary `#94A3B8`, muted/labels `#5B6B7C`.
- Section labels (uppercase, tracked): `#5B6B7C`, 11px, letter-spacing 0.12em.

Accents (semantic):
- **Signal cyan** `#22D3EE` (brand, Signal Core rings, waveforms, active nav glow). Secondary teal `#2DD4BF`.
- **Ready/Sent green** `#22C55E` (ready badges, Send/Insert primary buttons, high confidence, live dots). Bright `#34D399`.
- **Select blue** `#3B82F6` (selected card border, links, Raw→Refined pipeline text, active toggle). Light `#60A5FA`.
- **Warn amber** `#F59E0B` (recoverable, restore, failed-to-send, mid confidence 60s).
- **Danger red** `#EF4444` (delete, failed).
- Persona signature colors: Natural=cyan `#22D3EE`, Direct=green `#22C55E`, Warm=orange `#F59E0B`, Professional=purple `#A855F7`, Playful=pink `#EC4899`. These tint that persona's waveform + slider fills.

Confidence scale (bar + %): ≥85 green `#22C55E`; 70–84 also green but the mock uses blue `#3B82F6` for "unsent/draft" items; 60–69 amber `#F59E0B`; <60 amber→red. Rule: color encodes STATUS more than raw number — sent+high=green, draft=blue, recoverable/low=amber.

### Typography
- Family: Inter / SF Pro-like system sans. (Use the app's existing font stack; if none, add Inter.)
- Refined-message hero: ~44–48px, weight 300 (light), line-height 1.15, primary text. This is the visual centerpiece of Talk + Review Deck.
- Workspace H1 ("TALK", "LIBRARY", "STUDIO"): ~30px, weight 600, tight tracking; subtitle beneath in secondary color ~14px.
- Section labels: 11px uppercase tracked (see above).
- Body: 14px; small/meta: 12–13px.

### Spacing / radius / elevation
- Spacing scale: 4 / 8 / 12 / 16 / 20 / 24 / 32.
- Radius: cards 14px, buttons/pills 10px, small chips 8px, the big message card 16px.
- Card elevation: 1px hairline border + very soft shadow `0 1px 0 rgba(255,255,255,0.02) inset, 0 8px 24px rgba(0,0,0,0.35)`.
- Selected card: 1.5px `#3B82F6` border + faint blue glow `0 0 0 1px rgba(59,130,246,.4), 0 0 24px rgba(59,130,246,.12)`.

## 3. Shared app shell (all main workspaces)

Three columns + persistent bottom bar. Grid: `[nav 96px] [center 1fr] [context 320px]`, status bar full-width below.

### 3a. Left nav rail (96px, full height)
- Top: wordmark stack (BetterFingers / SIGNAL DESK).
- Primary nav (large rounded-square icon buttons, ~64px, icon + label beneath):
  1. **Talk** (waveform-bars icon) — active state: cyan-tinted fill, cyan glow, cyan label.
  2. **Library** (list icon)
  3. **Studio** (waveform icon)
  - hairline divider
  4. **Utilities** (wrench icon)
  5. **Settings** (gear icon)
- Bottom: version chip (orb avatar + "BetterFingers v1.2.0").
- Inactive icons: muted `#5B6B7C` on transparent; hover raises to card surface.

### 3b. Center header (per workspace)
- H1 + subtitle (left). Context pill (right): `Signal Core ●` / `Persona Foundry ●`.
- Talk also shows a breadcrumb under H1: `Capture → Refine → Send`.

### 3c. Right context panel (320px, collapsible)
- Header: `CONTEXT` + `«` collapse chevron (collapses to a thin rail; `‹ Hide Panel` button at bottom also collapses).
- Contents are workspace-specific (see §4–6). Uses section labels + `?` help affordances.

### 3d. Bottom status bar (full width, ~64px, always visible)
Seven cells, each = small icon + stacked (LABEL / value) + optional mini-viz:
`MIC Live` (+mini waveform) · `STT Ready ●` (green dot +mini wave) · `LLM Local ●` (brain icon, green dot) · `PERSONA Natural` (wave icon) · `DESTINATION Discord` (discord icon) · `LATENCY 1.2 sec` (+mini line graph) · `⋮` overflow.
- Live dots green when healthy; amber/red on degraded. This bar is the home for the existing runtime/health status + doctor summary.

## 4. TALK workspace (`01_talk_workspace.png`)
Center, top→bottom:
- **Signal Core ring** (hero): concentric tech rings (segmented arcs, cyan) around a centered live input waveform; `● LISTENING / Voice input detected` label upper-left; `-18 dB` vertical level meter at right edge of the ring; center hint `Hold Ctrl + Space / Speak naturally`. Ring pulses/reacts to mic amplitude. (This supersedes the current glitch-ring.js overlay ring — reuse/upgrade it.)
- **Refined Message card** (16px radius, raised):
  - Header row: `✨ REFINED MESSAGE` (left) + `✓ READY` green badge (right).
  - Hero refined text (44–48px light).
  - Meta strip (4 cells): RAW TRANSCRIPT (quoted lowercase raw), CONFIDENCE (94% + green bar), PERSONA (chip), DESTINATION (chip).
  - Action row: `Raw Transcript`, `Listen`, `Revise` (secondary buttons) + `Send / Insert` (green primary, split-button with ▾ for the copy/insert/send variants).

Right context panel (Talk): PERSONA dropdown (icon + name + one-line descriptor) · DESTINATION dropdown (app icon + channel) · DELIVERY segmented (Send / Insert / Copy) · CONFIDENCE (% + Low↔High slider) · PROCESSING MODE (Local ● card, green when on-device; this is where cloud/local + model residency surfaces) · ADVANCED ("Show advanced options ▾" → expands to the deeper knobs) · `‹ Hide Panel`.

## 5. LIBRARY workspace (`02_library_workspace.png`)
Center:
- Search bar (full width) `Search messages, personas, or destinations…` + filter-sliders icon button.
- Filter chip row: `All` (active blue) · `📌 Pinned` · `⊘ Unsent` · `ⓘ Recoverable` · `✓ Sent` · `Persona ▾` · `Destination ▾` · `Date ▾`.
- **Timeline list** grouped by day (`TODAY`, `YESTERDAY`), left gutter = time + status glyph (pin/sent/warn/draft-circle), connected by a faint vertical line. Each **message card**:
  - Title = message preview; pipeline `Raw → Refined → Sent` (color-coded by stage/status).
  - Persona chip + Destination chip (Discord/Slack/Gmail/Email icons).
  - CONFIDENCE % + colored bar.
  - Waveform thumbnail + duration `0:06`.
  - Status line: `✓ Sent • Today, 10:33 AM` / `● Failed to send ●` (amber) / `● Unsent • Draft`.
  - Selected card = blue border.
- Footer: `1–6 of 128 items` · `Load more ▾`.

Right context panel (Library, "SELECTED ITEM"): pin toggle · RAW TRANSCRIPT box (text + time) · ✨ REFINED MESSAGE box (text + confidence) · STATUS (✓ Sent successfully / time) · PERSONA + DESTINATION dropdowns · AUDIO player (waveform + 0:06 + ▶) · ACTIONS grid (Reopen, Listen, Duplicate, Pin, **Delete** red) · RESTORE / RESEND (Restore amber, Resend green).
- This whole workspace = the existing draft history + recordings + Message Rescue/recovery, unified. Maps to draft_queue, history, recordings, recovery/restore, resend.

## 6. STUDIO workspace (`03_studio_workspace.png`)
Left column — **PERSONAS** grid: `PERSONAS` + `+ New Persona`. Persona cards (2-wide) each: name, per-persona colored waveform signature, and mini slider bars for **Warmth / Directness / Detail / Formality / Confidence**. Selected = blue border + ✓. (Cards: Natural, Direct, Warm, Professional, Playful, …)

Center — **selected persona detail**:
- Header: 🎙 name + `Active` badge + edit ✏ / duplicate ⧉ / ⋮.
- Description paragraph.
- **EXAMPLE REWRITES** table: INPUT → OUTPUT rows each with a ▶ play (few-shot examples).
- INPUT EXAMPLE / OUTPUT (Live preview) / WHY THIS WORKS three-column card (tone + length + bullet rationale).
- Action row: `Test Persona`, `Stress Test`, `Save`, `Publish Preset` (green split-button).
- **VOICE & DELIVERY** blend strip: "Blend shapes how your persona sounds…" + voice cards (Clarity Core 58% selected, Warmth Air 28%, Presence Boost 14%, `+ Add Voice`) + `Preview ▶ "…" / Output` waveform.

Right context panel (Studio, "SELECTED PERSONA"): persona card · DESCRIPTION · STATS (Examples 128, Reliability 94% bar) · PREFERRED DESTINATIONS (app icons) · PAIRED VOICE dropdown · LAST UPDATED · TAGS (chips + `+`) · `‹ Hide Panel`.
- Maps to: personas (Foundry + wizard + refine/draft helpers we just built), few-shot examples, reliability score, tags, preferred destinations, voice blend (voice_blend / voice presets / modulation = Clarity Core/Warmth Air/Presence Boost), TTS preview/read-aloud.

## 7. OVERLAYS (`04_overlay_review_deck.png`) — floating, over the desktop
Two glassmorphic floating components (these replace/upgrade overlay.html + review-overlay.html):
- **Signal Core capture overlay**: circular ring + centered `BetterFingers / SIGNAL CORE` + live waveform + `00:12` timer + `Voice input detected` (green) + Stop ■ + Close ✕. Below: Destination chip + Persona dropdown + `● Recording…`. A dotted connector animates toward the Review Deck.
- **Review Deck overlay**: `✨ REVIEW DECK` + `SIGNAL CORE ●` + `✓ READY`; hero refined text; RAW TRANSCRIPT (collapsible ▲) + waveform player `00:12 ▶`; three cells DESTINATION / PERSONA / CONFIDENCE; actions `Listen`, `Revise`, `Insert Message` (green split-button).
- Global hint pill: `Press Alt + Space to capture`.
- These are frameless Electron windows; keep the existing IPC/status wiring, restyle to the mock. Honor auto-send / review-first / confidence-gating behavior already in the pipeline.

## 8. Feature-preservation mapping (fill from CURRENT_UI_INVENTORY.md)
Every current surface must map into: **Talk** (live capture/refine/send + delivery + processing mode), **Library** (history/recovery/resend/recordings), **Studio** (personas/foundry/wizard/voice/TTS), **Utilities** (dictionary, macros, wake word + training, audio device select, hotkey/controller binding, model downloads/residency, support report, export/import profile, privacy wipe, diagnostics/doctor), **Settings** (all profile keys grouped), **Status bar** (runtime/health/latency), **Overlays** (capture + review). Utilities & Settings are not mocked in detail — director will spec them in the same visual language, and NOTHING from the inventory may be omitted.

## 9. Build order (phased; director does visual QA each phase by screenshot)
1. **Foundation**: design tokens (CSS variables) + app shell (nav rail, header, context panel frame, status bar) + workspace router. No feature logic yet; static shell matching the mock chrome.
2. **Talk** workspace wired to the live pipeline (reuse existing draft/runtime feature modules behind the new markup).
3. **Library** (history + recovery + resend).
4. **Studio** (personas + voice, reusing personas.js/voiceStudio.js).
5. **Utilities + Settings** (everything else from the inventory — the catch-all that guarantees no feature is lost).
6. **Overlays** (capture + Review Deck restyle).
7. **Polish + a11y + light/dark** and full inventory gate re-check.

## 10. Verification protocol (director)
For each phase, the director renders the built markup in the browser pane and screenshots it, comparing against the corresponding mockup for: layout proportions, color accuracy, type scale, the Signal Core ring, spacing, and that every inventory control is present and wired. Workers do NOT self-certify visual fidelity.
