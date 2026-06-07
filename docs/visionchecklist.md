# Source Arcanum Studio Dream Checklist

Built from your vision: **BetterFingers mutates into a local-first AI storyboarding/comic/anime studio**, starting with voiced comic reels, then growing toward low-frame animation, then full anime episode generation. The uploaded PDF supports the same direction: specialized agents, deterministic tool use, GEST/event graphs, continuity control, and separating creative reasoning from programmatic validation.  BetterFingers already has useful base pieces: Electron app shell, FastAPI backend, local LLM sidecar, STT, TTS, profiles, drafts, diagnostics, graph endpoints, and project generation scaffolding.   

Legend:

```text
[MVP] = first working proof
[V1] = first real release
[V2] = stronger studio system
[DREAM] = full insane version, because apparently we are poking Netflix with a locally hosted stick
```

---

# 1. Product Identity

* [ ] **[MVP]** Rename the expanded vision internally as **Source Arcanum Studio**.
* [ ] **[MVP]** Treat BetterFingers as the current app/kernel, not something sacred that must stay small.
* [ ] **[V1]** Add **Studio Mode** inside BetterFingers.
* [ ] **[V1]** Keep BetterFingers’ voice-to-text, rewrite, TTS, and local model features as reusable core systems.
* [ ] **[V2]** Split into two products/repos if useful:

  * [ ] BetterFingers: local dictation/rewrite assistant.
  * [ ] Source Arcanum Studio: local AI story/comic/anime studio.
* [ ] **[DREAM]** Build an open-source creator-owned alternative to corporate streaming slop engines.
* [ ] **[DREAM]** Make the app feel like a personal AI animation studio, not a prompt box wearing a trench coat.

---

# 2. Core Philosophy

* [ ] **[MVP]** Build a **studio planning app first**, not a raw anime generator.
* [ ] **[MVP]** Prioritize continuity, story quality, and user control over raw frame count.
* [ ] **[MVP]** Use agents to create structured plans, not just prose blobs.
* [ ] **[MVP]** Let LLMs fill creative gaps, but do not let them casually destroy canon like a drunk screenwriter.
* [ ] **[V1]** Use deterministic code for:

  * [ ] file creation
  * [ ] database writes
  * [ ] project export
  * [ ] render queue tracking
  * [ ] validation
  * [ ] approvals
  * [ ] status reporting
* [ ] **[V1]** Use agents for:

  * [ ] story planning
  * [ ] worldbuilding
  * [ ] character design
  * [ ] dialogue
  * [ ] panel planning
  * [ ] visual prompting
  * [ ] continuity criticism
* [ ] **[V1]** Keep every agent narrow enough to do one job well.
* [ ] **[V2]** Make the system agentic but not chaotic.
* [ ] **[DREAM]** Make the user feel like producer/director/owner of the story.

---

# 3. Output Roadmap

## MVP Output

* [ ] **[MVP]** Generate a **60-second voiced comic reel**.
* [ ] **[MVP]** Use around **12 panels**, roughly 5 seconds each.
* [ ] **[MVP]** Include:

  * [ ] generated story premise
  * [ ] world bible
  * [ ] character bible
  * [ ] panel plan
  * [ ] dialogue/narration
  * [ ] local TTS audio
  * [ ] subtitles
  * [ ] image prompts
  * [ ] placeholder or real images
  * [ ] continuity report
* [ ] **[MVP]** Export as a simple preview reel or folder.

## V1 Output

* [ ] **[V1]** Generate a polished scrolling comic strip.
* [ ] **[V1]** Add voice timing.
* [ ] **[V1]** Add subtitles.
* [ ] **[V1]** Add basic motion:

  * [ ] scroll
  * [ ] pan
  * [ ] slow zoom
  * [ ] fade
  * [ ] panel slide
* [ ] **[V1]** Export to MP4.
* [ ] **[V1]** Allow rerendering individual bad panels.

## V2 Output

* [ ] **[V2]** Generate longer 3–5 minute voiced comic episodes.
* [ ] **[V2]** Add multiple scenes per reel.
* [ ] **[V2]** Add better music/SFX layering.
* [ ] **[V2]** Add limited animation tricks:

  * [ ] mouth flaps
  * [ ] eye blinks
  * [ ] hair movement
  * [ ] background movement
  * [ ] camera movement
* [ ] **[V2]** Add image-to-video per shot where continuity allows.

## Dream Output

* [ ] **[DREAM]** Generate 10-minute episodes.
* [ ] **[DREAM]** Generate 25-minute anime episodes.
* [ ] **[DREAM]** Support season-level continuity.
* [ ] **[DREAM]** Render full animated scenes without melting characters into cursed watercolor soup.
* [ ] **[DREAM]** Let users create long-running personal shows.

---

# 4. User Experience

* [ ] **[MVP]** User can talk to the app or type into it.
* [ ] **[MVP]** Intake agent asks questions back and forth.
* [ ] **[MVP]** User can provide:

  * [ ] vague idea
  * [ ] detailed premise
  * [ ] written scene
  * [ ] full story text
  * [ ] preferred genre
  * [ ] preferred tone
  * [ ] visual style
  * [ ] character ideas
* [ ] **[MVP]** App extracts what the user wants.
* [ ] **[MVP]** App asks clarifying questions until the user says stop or approval threshold is met.
* [ ] **[V1]** User can select detail level:

  * [ ] “Just make something cool”
  * [ ] “Ask me some questions”
  * [ ] “Let me approve everything”
  * [ ] “I’m producing this seriously”
* [ ] **[V1]** User can approve/reject:

  * [ ] premise
  * [ ] world bible
  * [ ] characters
  * [ ] character art
  * [ ] script
  * [ ] panel plan
  * [ ] voices
  * [ ] final reel
* [ ] **[V1]** User can ask the app why it made a choice.
* [ ] **[V1]** User can regenerate a weak piece without regenerating the whole project.
* [ ] **[V2]** User can control the studio from phone through secure tunnel/local remote UI.
* [ ] **[V2]** App can send previews to phone for approval.
* [ ] **[DREAM]** User can casually talk to it like a producer and get an evolving show.

---

# 5. Studio Modes

* [ ] **[MVP]** Add **Studio Mode** tab.
* [ ] **[MVP]** Add **New Project** flow.
* [ ] **[MVP]** Add **Story Seed** intake.
* [ ] **[MVP]** Add **Generated Plan** screen.
* [ ] **[MVP]** Add **Approval Queue**.
* [ ] **[V1]** Add modes:

  * [ ] Writer Mode
  * [ ] Producer Mode
  * [ ] Worldbuilder Mode
  * [ ] Character Studio
  * [ ] Comic Reel Builder
  * [ ] Render Queue
  * [ ] Continuity Report
  * [ ] Settings Agent
* [ ] **[V2]** Add timeline view.
* [ ] **[V2]** Add story graph view.
* [ ] **[V2]** Add character relationship map.
* [ ] **[DREAM]** Add full studio dashboard:

  * [ ] agents
  * [ ] current task graph
  * [ ] render workers
  * [ ] story canon
  * [ ] queued approvals
  * [ ] hardware usage
  * [ ] production timeline

---

# 6. Agent Roster

## Required MVP Agents

* [ ] **[MVP]** **User Intake Agent**

  * [ ] Talks to user.
  * [ ] Asks questions.
  * [ ] Extracts story intent.
  * [ ] Extracts user preferences.
  * [ ] Determines how much control the user wants.

* [ ] **[MVP]** **Producer / Headmaster Agent**

  * [ ] Orchestrates pipeline.
  * [ ] Decides which agent works next.
  * [ ] Waits for dependencies.
  * [ ] Prevents agents from overstepping.
  * [ ] Sends structured tasks to specialist agents.

* [ ] **[MVP]** **World Builder Agent**

  * [ ] Creates world rules.
  * [ ] Creates locations.
  * [ ] Creates factions/groups.
  * [ ] Defines magic/tech/social rules.
  * [ ] Generates world context for scenes.

* [ ] **[MVP]** **Character / NPC Creator Agent**

  * [ ] Creates major characters.
  * [ ] Creates NPCs.
  * [ ] Defines personality.
  * [ ] Defines speech style.
  * [ ] Defines goals/secrets/conflicts.
  * [ ] Defines visual description.
  * [ ] Defines voice profile.

* [ ] **[MVP]** **Story Planner Agent**

  * [ ] Builds plot.
  * [ ] Creates beats.
  * [ ] Tracks callbacks.
  * [ ] Tracks foreshadowing.
  * [ ] Tracks emotional arc.
  * [ ] Keeps the story from degenerating into “and then stuff happened.”

* [ ] **[MVP]** **Dialogue / Performance Agent**

  * [ ] Writes character lines.
  * [ ] Writes narration.
  * [ ] Applies character voice.
  * [ ] Adds emotional tags.
  * [ ] Estimates duration.

* [ ] **[MVP]** **Panel Designer Agent**

  * [ ] Converts beats into comic panels.
  * [ ] Chooses camera angle.
  * [ ] Chooses composition.
  * [ ] Tracks visible characters.
  * [ ] Attaches dialogue/audio to panels.

* [ ] **[MVP]** **Continuity Critic Agent**

  * [ ] Reviews story continuity.
  * [ ] Reviews character consistency.
  * [ ] Reviews world logic.
  * [ ] Flags contradictions.
  * [ ] Suggests repairs.

## V1 Agents

* [ ] **[V1]** **Settings / Hardware Agent**

  * [ ] Detects GPU/VRAM/CPU/RAM/disk.
  * [ ] Recommends models.
  * [ ] Warns user when a model will be slow or impossible.
  * [ ] Picks sane defaults.
  * [ ] Prevents “I clicked full episode and now my PC hates me.”

* [ ] **[V1]** **Visual Prompt Agent**

  * [ ] Converts structured panel specs into image prompts.
  * [ ] Uses character sheets.
  * [ ] Uses style bible.
  * [ ] Uses location references.
  * [ ] Saves seeds/model/settings.

* [ ] **[V1]** **TTS / Voice Agent**

  * [ ] Assigns voices.
  * [ ] Generates narration.
  * [ ] Generates character dialogue.
  * [ ] Tracks voice continuity.
  * [ ] Supports emotional direction.

* [ ] **[V1]** **Render Agent**

  * [ ] Runs image generation.
  * [ ] Tracks render queue.
  * [ ] Saves output paths.
  * [ ] Supports rerenders.
  * [ ] Never rewrites canon by itself.

* [ ] **[V1]** **Approval Agent**

  * [ ] Presents generated pieces to user.
  * [ ] Tracks approved/rejected/edit-needed state.
  * [ ] Locks canon when approved.
  * [ ] Routes rejected items back to the right specialist.

## Dream Agents

* [ ] **[DREAM]** **Season Showrunner Agent**
* [ ] **[DREAM]** **Lore Archivist Agent**
* [ ] **[DREAM]** **Map Cartographer Agent**
* [ ] **[DREAM]** **Combat Choreographer Agent**
* [ ] **[DREAM]** **Comedy Punch-Up Agent**
* [ ] **[DREAM]** **Emotional Arc Agent**
* [ ] **[DREAM]** **Music/SFX Director Agent**
* [ ] **[DREAM]** **Vision Critic Agent**
* [ ] **[DREAM]** **Animation Supervisor Agent**
* [ ] **[DREAM]** **Release/Publishing Agent**

---

# 7. Story Memory

* [ ] **[MVP]** Create persistent **Project Memory**.
* [ ] **[MVP]** Store:

  * [ ] title
  * [ ] premise
  * [ ] genre
  * [ ] tone
  * [ ] style
  * [ ] user preferences
  * [ ] forbidden tropes
  * [ ] desired tropes
* [ ] **[MVP]** Create **World Bible**.
* [ ] **[MVP]** Create **Character Bible**.
* [ ] **[MVP]** Create **Episode Memory**.
* [ ] **[MVP]** Create **Minute/Reel Memory**.
* [ ] **[V1]** Add layered memory:

  * [ ] project memory
  * [ ] season memory
  * [ ] episode memory
  * [ ] minute memory
  * [ ] panel memory
* [ ] **[V1]** Archive raw outputs but extract canon facts.
* [ ] **[V1]** Compress old minutes into summaries.
* [ ] **[V1]** Save important objects/props, like “black dagger acquired.”
* [ ] **[V1]** Save callbacks and unresolved plot hooks.
* [ ] **[V1]** Track when a character learns something.
* [ ] **[V1]** Track when the audience learns something.
* [ ] **[V2]** Add automatic canon extraction.
* [ ] **[V2]** Add memory compaction agent.
* [ ] **[DREAM]** Maintain long-running series memory without losing plot threads.

---

# 8. Canon Rules

* [ ] **[MVP]** Agents may invent missing details.
* [ ] **[MVP]** Agents may create new characters.
* [ ] **[MVP]** Agents may create new locations.
* [ ] **[MVP]** Agents may create new plot hooks.
* [ ] **[MVP]** Agents may not overwrite locked canon.
* [ ] **[MVP]** Approved canon becomes protected.
* [ ] **[V1]** Agents can propose canon edits.
* [ ] **[V1]** User can approve canon changes.
* [ ] **[V1]** User can reject canon changes.
* [ ] **[V1]** App flags contradictions automatically.
* [ ] **[V1]** App can auto-fix minor contradictions.
* [ ] **[V1]** User can choose approval strictness:

  * [ ] Autopilot
  * [ ] Producer
  * [ ] Strict
* [ ] **[V2]** Add branching:

  * [ ] canon
  * [ ] alternate take
  * [ ] failed render
  * [ ] old revision
* [ ] **[DREAM]** Allow rewinding story from an earlier approved point.

---

# 9. Continuity Types

* [ ] **[MVP]** Story continuity.
* [ ] **[MVP]** Character continuity.
* [ ] **[MVP]** World continuity.
* [ ] **[MVP]** Scene continuity.
* [ ] **[V1]** Visual continuity.
* [ ] **[V1]** Voice continuity.
* [ ] **[V1]** Timeline continuity.
* [ ] **[V1]** Object/prop continuity.
* [ ] **[V1]** Relationship continuity.
* [ ] **[V1]** Emotional continuity.
* [ ] **[V2]** Shot-to-shot continuity.
* [ ] **[V2]** Frame-level continuity.
* [ ] **[V2]** Season continuity.
* [ ] **[DREAM]** Project-wide continuity across many episodes/seasons.

---

# 10. Character System

* [ ] **[MVP]** Store each character as structured data.
* [ ] **[MVP]** Include:

  * [ ] name
  * [ ] role
  * [ ] personality
  * [ ] goals
  * [ ] fears
  * [ ] secrets
  * [ ] relationships
  * [ ] speech style
  * [ ] visual description
  * [ ] outfit
  * [ ] color palette
  * [ ] voice profile
* [ ] **[MVP]** Generate character bible.
* [ ] **[V1]** Generate character sheet image.
* [ ] **[V1]** Generate:

  * [ ] front view
  * [ ] side view
  * [ ] expression sheet
  * [ ] outfit sheet
  * [ ] pose sheet
* [ ] **[V1]** User approves character sheet before major rendering.
* [ ] **[V1]** Character references are reused in image prompts.
* [ ] **[V1]** Character speech style informs dialogue.
* [ ] **[V1]** Character memory tracks:

  * [ ] what they know
  * [ ] what they want
  * [ ] what changed
  * [ ] what they carry
  * [ ] current mood
  * [ ] current injury/status
* [ ] **[V2]** Add character relationship graph.
* [ ] **[V2]** Add character arc tracker.
* [ ] **[DREAM]** Characters act like persistent cast members across seasons.

---

# 11. World System

* [ ] **[MVP]** World Builder creates world bible.
* [ ] **[MVP]** Store:

  * [ ] setting
  * [ ] genre rules
  * [ ] tone rules
  * [ ] major locations
  * [ ] factions
  * [ ] magic/tech system
  * [ ] social rules
  * [ ] danger level
* [ ] **[MVP]** World rules are available to story planner.
* [ ] **[V1]** World Builder creates scene-relevant location descriptions.
* [ ] **[V1]** World Builder creates location visual prompts.
* [ ] **[V1]** Store locations as reusable assets.
* [ ] **[V1]** Track which scenes happen where.
* [ ] **[V2]** Generate simple maps.
* [ ] **[V2]** Link maps to locations and story events.
* [ ] **[V2]** Use map context in scene planning.
* [ ] **[DREAM]** Generate expanding world tree:

  * [ ] regions
  * [ ] towns
  * [ ] factions
  * [ ] dungeons
  * [ ] politics
  * [ ] history
  * [ ] economy
  * [ ] rumors
  * [ ] story hooks

---

# 12. Plot and Writing System

* [ ] **[MVP]** Generate a premise from user input.
* [ ] **[MVP]** Generate one-minute story arc.
* [ ] **[MVP]** Generate story beats.
* [ ] **[MVP]** Generate narration.
* [ ] **[MVP]** Generate character dialogue.
* [ ] **[MVP]** Track callbacks.
* [ ] **[MVP]** Track important items.
* [ ] **[V1]** Add foreshadowing tracker.
* [ ] **[V1]** Add unresolved plot thread tracker.
* [ ] **[V1]** Add emotional arc.
* [ ] **[V1]** Add character-specific motivation checks.
* [ ] **[V1]** Add pacing controls:

  * [ ] slow
  * [ ] balanced
  * [ ] action-heavy
  * [ ] dialogue-heavy
  * [ ] comedy-heavy
  * [ ] mystery-heavy
* [ ] **[V2]** Add episode-level arcs.
* [ ] **[V2]** Add season-level arcs.
* [ ] **[V2]** Add “shopping episode memory compression,” meaning minor scenes can matter only through extracted canon.
* [ ] **[DREAM]** Create stories with long-term payoff, callbacks, character quirks, and “that one thing from episode 2 mattered” energy.

---

# 13. Dialogue System

* [ ] **[MVP]** Dialogue is generated from character bible + story beat.
* [ ] **[MVP]** Dialogue agent does not rewrite canon.
* [ ] **[MVP]** Lines include:

  * [ ] speaker
  * [ ] line
  * [ ] emotion
  * [ ] delivery note
  * [ ] estimated duration
* [ ] **[V1]** User can edit dialogue line-by-line.
* [ ] **[V1]** Dialogue uses character-specific speech style.
* [ ] **[V1]** Dialogue avoids generic AI mush.
* [ ] **[V1]** Dialogue can be regenerated per character.
* [ ] **[V1]** Dialogue can be locked before audio generation.
* [ ] **[V2]** Dialogue agent can do passes:

  * [ ] naturalness pass
  * [ ] character voice pass
  * [ ] pacing pass
  * [ ] anime/drama punch-up pass
  * [ ] continuity pass
* [ ] **[DREAM]** Dialogue feels like real character writing, not beige corporate fanfic.

---

# 14. Comic Panel System

* [ ] **[MVP]** Generate 12 panels for a 60-second reel.
* [ ] **[MVP]** Each panel stores:

  * [ ] panel number
  * [ ] duration
  * [ ] scene beat
  * [ ] location
  * [ ] visible characters
  * [ ] action
  * [ ] camera angle
  * [ ] composition
  * [ ] dialogue attached
  * [ ] narration attached
  * [ ] image prompt
  * [ ] negative prompt
* [ ] **[V1]** User can approve panel plan before rendering.
* [ ] **[V1]** User can regenerate individual panel prompts.
* [ ] **[V1]** User can reorder panels.
* [ ] **[V1]** Panel system tracks continuity requirements:

  * [ ] outfit
  * [ ] props
  * [ ] injuries
  * [ ] location state
  * [ ] lighting
  * [ ] mood
* [ ] **[V2]** Panels can become shots.
* [ ] **[V2]** Shots can become animated clips.
* [ ] **[DREAM]** Panel system evolves into storyboard + animatic + scene graph.

---

# 15. Visual Generation

* [ ] **[MVP]** Start with images only.
* [ ] **[MVP]** Avoid 24fps generation.
* [ ] **[MVP]** Generate panel prompts.
* [ ] **[MVP]** Save prompt, negative prompt, seed, model, and settings.
* [ ] **[V1]** Integrate image backend:

  * [ ] ComfyUI preferred
  * [ ] local Flux-compatible workflows
  * [ ] anime-capable models
* [ ] **[V1]** Generate character reference sheets.
* [ ] **[V1]** Generate location references.
* [ ] **[V1]** Use structured character data and free-text prompt blending.
* [ ] **[V1]** Add reroll button.
* [ ] **[V1]** Add “repair panel” workflow.
* [ ] **[V1]** Add preview quality vs final quality.
* [ ] **[V2]** Add upscaling.
* [ ] **[V2]** Add image consistency review.
* [ ] **[V2]** Add optional LoRA support later, not as a dependency.
* [ ] **[DREAM]** Generate visually stable anime scenes across long episodes.

---

# 16. Video / Reel Assembly

* [ ] **[MVP]** Assemble still panels into a preview.
* [ ] **[MVP]** Sync audio to panels.
* [ ] **[MVP]** Add subtitles.
* [ ] **[MVP]** Add simple scroll/slide effect.
* [ ] **[V1]** Export MP4.
* [ ] **[V1]** Export project folder.
* [ ] **[V1]** Export images and audio separately.
* [ ] **[V1]** Allow rerendering one panel without rebuilding the whole reel.
* [ ] **[V2]** Add limited motion:

  * [ ] zoom
  * [ ] pan
  * [ ] mouth flaps
  * [ ] eye blinks
  * [ ] parallax
* [ ] **[V2]** Add image-to-video per shot.
* [ ] **[DREAM]** Move from comic reel to full anime episode.

---

# 17. Audio / Voice System

* [ ] **[MVP]** Use local TTS.
* [ ] **[MVP]** Generate narration.
* [ ] **[MVP]** Generate character voice lines.
* [ ] **[MVP]** Save audio files per line.
* [ ] **[MVP]** Auto-generate subtitles from script.
* [ ] **[V1]** Each character has voice profile.
* [ ] **[V1]** Support emotional tags:

  * [ ] angry
  * [ ] tired
  * [ ] whispering
  * [ ] panicked
  * [ ] smug
  * [ ] calm
  * [ ] excited
* [ ] **[V1]** Voice lines are reviewed before visual final render.
* [ ] **[V1]** User can replay voice lines.
* [ ] **[V1]** User can regenerate individual lines.
* [ ] **[V1]** Voice continuity critic checks character voices.
* [ ] **[V2]** Add user-recorded voice references, consent-based.
* [ ] **[V2]** Add SFX.
* [ ] **[V2]** Add background music.
* [ ] **[DREAM]** Full audio drama-style performance with stable voices and emotion.

---

# 18. Copyright / IP Guardrails

* [ ] **[MVP]** Do not build around celebrity/anime actor voice cloning.
* [ ] **[MVP]** Do not ship prompts encouraging commercial use of copyrighted characters.
* [ ] **[MVP]** Encourage original characters/worlds.
* [ ] **[V1]** Add project setting:

  * [ ] personal/private fan-style use
  * [ ] original commercial-safe project
  * [ ] open-source/public release
* [ ] **[V1]** Add warnings around:

  * [ ] celebrity voices
  * [ ] copyrighted characters
  * [ ] trademarked worlds
  * [ ] “make Naruto but legally distinct” nonsense, humanity’s favorite lawsuit seed
* [ ] **[V1]** Allow stylistic inspiration without directly copying named IP.
* [ ] **[V2]** Add export report showing:

  * [ ] model used
  * [ ] assets used
  * [ ] user-owned/generated materials
  * [ ] copyright warnings
* [ ] **[DREAM]** Make creator-owned original anime the default.

---

# 19. Storage / Database

* [ ] **[MVP]** Use SQLite for indexed project memory.
* [ ] **[MVP]** Use project folders for assets.
* [ ] **[MVP]** Store generated media inside project folder.
* [ ] **[MVP]** Store bibles as Markdown/JSON exports.
* [ ] **[V1]** Project folder structure:

```text
SourceArcanumProjects/
  Project_Name/
    project.json
    studio.sqlite
    bibles/
      series_bible.md
      world_bible.md
      style_bible.md
    characters/
    locations/
    episodes/
    renders/
    audio/
    exports/
    logs/
```

* [ ] **[V1]** SQLite tables:

  * [ ] projects
  * [ ] user_preferences
  * [ ] bibles
  * [ ] characters
  * [ ] locations
  * [ ] episodes
  * [ ] minutes/reels
  * [ ] panels
  * [ ] dialogue_lines
  * [ ] assets
  * [ ] canon_events
  * [ ] approvals
  * [ ] continuity_warnings
  * [ ] tool_calls
  * [ ] render_jobs
  * [ ] model_profiles
* [ ] **[V1]** Add full project export ZIP.
* [ ] **[V1]** Add delete all generated data.
* [ ] **[V2]** Add project Git versioning.
* [ ] **[DREAM]** Full portable studio project format.

---

# 20. GEST / Graph System

* [ ] **[MVP]** Expand current graph save/load into early story graph. BetterFingers currently has simple `nodes` and `edges` graph endpoints, which can become the seed instead of decorative JSON confetti. 
* [ ] **[MVP]** Graph tracks:

  * [ ] characters
  * [ ] locations
  * [ ] objects
  * [ ] events
  * [ ] panels
  * [ ] dialogue
* [ ] **[V1]** Nodes include:

  * [ ] CharacterExists
  * [ ] LocationExists
  * [ ] PropExists
  * [ ] Action
  * [ ] DialogueLine
  * [ ] Panel
  * [ ] AudioCue
  * [ ] RenderArtifact
* [ ] **[V1]** Edges include:

  * [ ] before
  * [ ] after
  * [ ] causes
  * [ ] enables
  * [ ] prevents
  * [ ] requires
  * [ ] observes
  * [ ] interrupts
  * [ ] motivates
  * [ ] contrasts_with
* [ ] **[V1]** Validate graph before render.
* [ ] **[V1]** Reject circular dependencies.
* [ ] **[V1]** Return structured error to agent.
* [ ] **[V2]** Add transactional scene building.
* [ ] **[V2]** Add rollback on failed scene/panel creation.
* [ ] **[DREAM]** Full formal GEST engine powering long-form animation.

---

# 21. Validation System

* [ ] **[MVP]** Validate required fields before saving.
* [ ] **[MVP]** Validate canon references exist.
* [ ] **[MVP]** Validate each panel has:

  * [ ] duration
  * [ ] image prompt
  * [ ] scene beat
  * [ ] associated audio or narration
* [ ] **[V1]** Validate character consistency.
* [ ] **[V1]** Validate location consistency.
* [ ] **[V1]** Validate locked canon is not overwritten.
* [ ] **[V1]** Validate timeline order.
* [ ] **[V1]** Validate render job has all required assets.
* [ ] **[V1]** Send structured errors back to agents.
* [ ] **[V2]** Add action prerequisites:

  * [ ] must stand before walking
  * [ ] must hold object before using object
  * [ ] must enter location before interacting there
  * [ ] must know information before referencing it
* [ ] **[DREAM]** Full simulator-valid story logic.

---

# 22. Model Stack

* [ ] **[MVP]** Local-first.
* [ ] **[MVP]** Use current llama-server sidecar path where practical. BetterFingers already uses a local `llama-server` backend for inference. 
* [ ] **[MVP]** Minimum target: Gemma-style 12B local model class.
* [ ] **[V1]** Add model router.
* [ ] **[V1]** Support multiple local providers:

  * [ ] llama.cpp / llama-server
  * [ ] Ollama
  * [ ] LM Studio
  * [ ] ComfyUI for images
* [ ] **[V1]** Allow user to plug in Hugging Face models.
* [ ] **[V1]** Cheap/fast models handle:

  * [ ] extraction
  * [ ] tagging
  * [ ] formatting
  * [ ] simple validation
* [ ] **[V1]** Stronger models handle:

  * [ ] story planning
  * [ ] continuity
  * [ ] worldbuilding
  * [ ] final review
* [ ] **[V2]** Vision models review images.
* [ ] **[V2]** Multi-model critique.
* [ ] **[DREAM]** Users with giant VRAM monsters can run huge local models and get better outputs.

---

# 23. Hardware / Settings Agent

* [ ] **[MVP]** Detect OS.
* [ ] **[MVP]** Detect CPU/RAM.
* [ ] **[MVP]** Detect GPU/VRAM if possible.
* [ ] **[MVP]** Detect disk space.
* [ ] **[V1]** Recommend model size based on hardware.
* [ ] **[V1]** Recommend image resolution based on VRAM.
* [ ] **[V1]** Recommend preview/final quality settings.
* [ ] **[V1]** Warn user when:

  * [ ] model is too large
  * [ ] render may take hours
  * [ ] disk space is low
  * [ ] GPU not detected
  * [ ] CPU-only fallback will be slow
* [ ] **[V1]** Create performance modes:

  * [ ] potato mode
  * [ ] balanced mode
  * [ ] high quality
  * [ ] overnight render
  * [ ] monster GPU mode
* [ ] **[V2]** Automatically configure ComfyUI/LLM/TTS workers.
* [ ] **[DREAM]** Hardware agent behaves like a local production engineer.

---

# 24. Render Queue

* [ ] **[MVP]** Add render job table.
* [ ] **[MVP]** Track:

  * [ ] status
  * [ ] queued
  * [ ] running
  * [ ] failed
  * [ ] complete
* [ ] **[MVP]** Render one panel at a time.
* [ ] **[V1]** Render panels in batch.
* [ ] **[V1]** Repair failed panels.
* [ ] **[V1]** Retry failed jobs.
* [ ] **[V1]** Estimate:

  * [ ] time
  * [ ] VRAM use
  * [ ] disk use
* [ ] **[V1]** Save:

  * [ ] prompt
  * [ ] seed
  * [ ] model
  * [ ] settings
  * [ ] output path
* [ ] **[V2]** Add preview render vs final render.
* [ ] **[V2]** Add overnight render mode.
* [ ] **[DREAM]** Distributed local render workers / microservices.

---

# 25. Approval System

* [ ] **[MVP]** Use current BetterFingers draft/approval concept as inspiration.
* [ ] **[MVP]** Approval states:

  * [ ] pending
  * [ ] approved
  * [ ] rejected
  * [ ] needs edit
  * [ ] locked
* [ ] **[MVP]** Approve:

  * [ ] premise
  * [ ] world bible
  * [ ] characters
  * [ ] script
  * [ ] panels
* [ ] **[V1]** Approve:

  * [ ] character sheets
  * [ ] voices
  * [ ] render previews
  * [ ] final export
* [ ] **[V1]** Add approval modes:

  * [ ] Autopilot
  * [ ] Producer
  * [ ] Strict
* [ ] **[V1]** Lock canon after approval.
* [ ] **[V1]** Reject sends item back to correct agent.
* [ ] **[V2]** Phone approval workflow.
* [ ] **[DREAM]** User can produce a full episode through lightweight approvals instead of babysitting every pixel.

---

# 26. Permissions

* [ ] **[MVP]** No internet by default.
* [ ] **[MVP]** Local-first storage.
* [ ] **[MVP]** Agents cannot delete project data without approval.
* [ ] **[MVP]** Agents cannot overwrite locked canon.
* [ ] **[V1]** Permission scopes:

  * [ ] read_project
  * [ ] write_project
  * [ ] edit_canon
  * [ ] create_assets
  * [ ] overwrite_assets
  * [ ] run_render_jobs
  * [ ] install_models
  * [ ] launch_local_processes
  * [ ] use_paid_api
  * [ ] access_internet
  * [ ] commit_to_github
  * [ ] delete_project_data
* [ ] **[V1]** User can permit paid APIs with budget limit.
* [ ] **[V1]** User can allow model installation.
* [ ] **[V1]** User can allow render jobs.
* [ ] **[V2]** Per-agent permissions.
* [ ] **[V2]** Per-project permissions.
* [ ] **[DREAM]** Safe autopilot mode that does real work without becoming a digital raccoon with root access.

---

# 27. Local / Remote Phone Control

* [ ] **[V1]** Local web dashboard option.
* [ ] **[V1]** Secure LAN access.
* [ ] **[V2]** Secure tunnel from PC/server to phone.
* [ ] **[V2]** Send previews to phone.
* [ ] **[V2]** User can approve/reject from phone.
* [ ] **[V2]** User can answer agent questions from phone.
* [ ] **[V2]** User can start/stop render jobs remotely.
* [ ] **[DREAM]** The user can produce a show from anywhere while the home PC/server grinds away like a loyal space heater.

---

# 28. Project Export

* [ ] **[MVP]** Export structured project JSON.
* [ ] **[MVP]** Export Markdown bibles.
* [ ] **[V1]** Export:

  * [ ] MP4 reel
  * [ ] subtitles
  * [ ] audio files
  * [ ] panel images
  * [ ] story bible
  * [ ] character bible
  * [ ] project ZIP
* [ ] **[V1]** Export report includes:

  * [ ] models used
  * [ ] prompts/settings saved internally
  * [ ] warnings
  * [ ] render time
* [ ] **[V2]** Export to YouTube-ready package.
* [ ] **[DREAM]** Full production archive for an episode or season.

---

# 29. GitHub / Open Source

* [ ] **[MVP]** Keep the project open-source.
* [ ] **[MVP]** Add design docs.
* [ ] **[MVP]** Add checklist/spec docs.
* [ ] **[V1]** Add GitHub issues for:

  * [ ] Studio Mode UI
  * [ ] SQLite project memory
  * [ ] agent workflow
  * [ ] comic reel pipeline
  * [ ] TTS/audio system
  * [ ] ComfyUI/image adapter
  * [ ] continuity critic
  * [ ] export pipeline
* [ ] **[V1]** Add contribution guide.
* [ ] **[V1]** Add local setup guide.
* [ ] **[V1]** Add hardware recommendations.
* [ ] **[V2]** Add plugin system.
* [ ] **[DREAM]** Build a community around open creator-owned anime/comic production.

---

# 30. Architecture

## Current Local V1 Architecture

* [ ] **[MVP]** Keep Electron UI.
* [ ] **[MVP]** Keep FastAPI backend.
* [ ] **[MVP]** Add studio modules inside backend.
* [ ] **[MVP]** Keep direct Python functions for deterministic work.
* [ ] **[V1]** Add internal service boundaries:

  * [ ] workflow engine
  * [ ] model router
  * [ ] memory/database layer
  * [ ] render adapter
  * [ ] TTS adapter
  * [ ] export service
* [ ] **[V1]** Avoid Kubernetes.
* [ ] **[V1]** Avoid heavy MCP-first architecture.
* [ ] **[V2]** Make workflow engine separable from UI adapter.
* [ ] **[V2]** Make render worker separable from workflow engine.
* [ ] **[DREAM]** Containerized microservice architecture:

  * [ ] UI adapter
  * [ ] workflow engine
  * [ ] LLM worker
  * [ ] image worker
  * [ ] audio worker
  * [ ] render/export worker
  * [ ] database/asset service

---

# 31. BetterFingers Reuse Checklist

* [ ] **[MVP]** Reuse FastAPI backend.
* [ ] **[MVP]** Reuse Electron shell.
* [ ] **[MVP]** Reuse STT for user intake.
* [ ] **[MVP]** Reuse TTS for preview voices.
* [ ] **[MVP]** Reuse local LLM engine.
* [ ] **[MVP]** Reuse profiles/settings ideas.
* [ ] **[MVP]** Reuse draft queue idea for approvals.
* [ ] **[MVP]** Extend graph endpoints into story graph.
* [ ] **[V1]** Replace simple project generator with studio project generator.
* [ ] **[V1]** Add Studio Mode routes.
* [ ] **[V1]** Add Studio Mode UI.
* [ ] **[V1]** Add model routing beyond one LLM role.
* [ ] **[V2]** Extract BetterFingers core into reusable modules.

---

# 32. MVP Build Order

This is the actual sane order. Naturally, it is less glamorous than “summon anime,” but it has the minor advantage of being buildable.

## Phase 1: Studio Foundation

* [ ] Create project folder structure.
* [ ] Create SQLite database.
* [ ] Create studio memory module.
* [ ] Add project create/load endpoints.
* [ ] Add bible/character/panel storage endpoints.
* [ ] Add approval states.

## Phase 2: Mock Pipeline

* [ ] User seed input.
* [ ] Mock world bible.
* [ ] Mock character bible.
* [ ] Mock one-minute story plan.
* [ ] Mock 12-panel plan.
* [ ] Mock dialogue.
* [ ] Mock continuity report.
* [ ] Show all in UI.

## Phase 3: Real LLM Pipeline

* [ ] Connect local LLM to intake.
* [ ] Generate real world bible.
* [ ] Generate real character bible.
* [ ] Generate real story plan.
* [ ] Generate real panel plan.
* [ ] Validate JSON.
* [ ] Store all outputs.

## Phase 4: Audio

* [ ] Generate TTS per line.
* [ ] Save audio files.
* [ ] Estimate timing.
* [ ] Attach audio to panels.
* [ ] Generate subtitles.

## Phase 5: Images

* [ ] Add ComfyUI/image adapter.
* [ ] Generate character sheet.
* [ ] Generate panel images.
* [ ] Save render metadata.
* [ ] Add rerender panel.

## Phase 6: Reel Export

* [ ] Assemble panels + audio.
* [ ] Add subtitles.
* [ ] Add simple scroll/zoom.
* [ ] Export MP4.
* [ ] Export project ZIP.

---

# 33. Dream Success Criteria

The dream version is successful when:

* [ ] A user can talk for 10–60 minutes and the app understands the show they want.
* [ ] The app builds a world that feels coherent.
* [ ] The app creates characters that stay visually and narratively consistent.
* [ ] The app writes scenes with callbacks, foreshadowing, and payoff.
* [ ] The app remembers the important dagger, scar, promise, joke, betrayal, or weird player habit.
* [ ] The app generates a voiced comic reel that is actually entertaining.
* [ ] The next reel remembers what happened in the previous reel.
* [ ] The user can fix weak spots without restarting everything.
* [ ] The system can grow from 1 minute to 5 minutes to 25 minutes.
* [ ] The app runs locally whenever possible.
* [ ] The project remains open-source.
* [ ] The user owns the story and files.
* [ ] The system does not depend on hidden cloud storage.
* [ ] The system does not require subscription nonsense.
* [ ] The pipeline is understandable, debuggable, and repairable.
* [ ] Someone can watch the result and think: “Wait, one person made this?”

---

