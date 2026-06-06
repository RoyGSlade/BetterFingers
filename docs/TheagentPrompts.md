Agent 1: Studio Kernel / Data Architect

Mission: Build the project memory foundation.

You are working in RoyGSlade/BetterFingers.

Goal:
Create the foundation for Source Arcanum Studio Mode as a local-first story/comic generation studio.

Do not build rendering yet.
Do not build internet access.
Do not build Kubernetes or microservices.

Implement or design:
1. Project folder structure for Source Arcanum projects.
2. SQLite schema for:
   - projects
   - user_preferences
   - bibles
   - characters
   - locations
   - episodes
   - minutes
   - panels
   - dialogue_lines
   - assets
   - canon_events
   - continuity_warnings
   - approvals
   - tool_calls
3. A Python module like studio_project.py or studio_memory.py.
4. FastAPI endpoints for:
   - create project
   - load project
   - save/get bible
   - create/update character
   - create episode
   - create minute
   - list panels
   - save continuity warning
   - approve/reject item
5. Keep all project assets inside a project folder.
6. Use SQLite for indexed memory.
7. Keep JSON export possible.
8. Add basic tests or test script.

Constraints:
- Keep architecture flat and readable.
- Use direct Python functions for deterministic work.
- No LLM calls inside database functions.
- No destructive deletes without explicit endpoint and confirmation.
Agent 2: Agent Workflow / Producer Pipeline

Mission: Build the first mock end-to-end studio workflow.

You are working in RoyGSlade/BetterFingers.

Goal:
Build the first Source Arcanum Studio workflow that turns a user story seed into a structured 60-second voiced comic reel plan.

Do not build real image rendering yet.
Do not build real video rendering yet.
Use mock outputs where needed.

Create a workflow module like studio_workflow.py.

The pipeline should:
1. Accept user story seed text.
2. Generate or mock:
   - project premise
   - world bible
   - character bibles
   - one-minute story plan
   - 12 panel specs
   - narration/dialogue lines
   - continuity summary
3. Store all outputs through the studio memory layer.
4. Return a structured response usable by Electron UI.
5. Include clear workflow states:
   - intake
   - world_building
   - character_building
   - story_planning
   - dialogue
   - panel_planning
   - approval_ready
6. Add retry/error handling.
7. Log tool/workflow steps.
8. Make every stage independently callable for testing.

Constraints:
- Producer/orchestrator routes work.
- Individual functions have one job.
- No giant mega-agent prompt.
- Use existing LLM engine only through a thin adapter.
- If LLM output fails JSON parsing, return repairable error.
Agent 3: Studio Mode UI / Approval Dashboard

Mission: Make the user able to see and approve the studio pipeline.

You are working in RoyGSlade/BetterFingers.

Goal:
Add a Source Arcanum Studio Mode UI to the Electron app.

Do not remove existing BetterFingers features unless necessary.
Do not build final render UI yet.

Create UI for:
1. New Studio Project
2. Story Seed / Talk-to-Agent input
3. Generated project premise
4. World bible preview
5. Character bible cards
6. 12-panel comic reel plan
7. Dialogue/narration view
8. Approval controls:
   - approve
   - reject
   - edit
   - regenerate
9. Continuity warning display
10. Export placeholder button

The UI should assume backend endpoints exist or will exist.
Use clean HTML/CSS/JS/Electron patterns already present in the app.
Make it simple enough that a non-technical user can follow.

Design principle:
The user should feel like they are producing a comic reel, not operating a nuclear submarine made of JSON.
Final v1 definition

Put this at the top of the project spec:

Source Arcanum Studio v1 is a local-first AI-assisted storyboarding and voiced comic reel generator.

It does not attempt full animation. It creates structured story canon, character/world bibles, panel plans, dialogue, voice lines, comic images, continuity checks, and an exportable scrolling comic reel.

The system prioritizes continuity, user control, local ownership, and modular agent workflows over raw generation volume.