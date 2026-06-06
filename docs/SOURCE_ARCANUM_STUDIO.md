Source Arcanum Studio v1 is a local-first AI-assisted storyboarding and voiced comic reel generator.

It does not attempt full animation. It creates structured story canon, character/world bibles, panel plans, dialogue, voice lines, comic images, continuity checks, and an exportable scrolling comic reel.

The system prioritizes continuity, user control, local ownership, and modular agent workflows over raw generation volume.

## Agent 1 Foundation

Agent 1 owns the local project memory kernel:

- Project folders live under the BetterFingers user data directory at `studio_projects/<project name>/`.
- Each project has a local `studio.db` SQLite database.
- Project assets are constrained to the project folder.
- The schema includes projects, user preferences, bibles, characters, locations, episodes, minutes, panels, dialogue lines, assets, canon events, continuity warnings, approvals, and tool calls.
- Deterministic memory functions live in `studio_memory.py`.
- FastAPI Studio endpoints are mounted under `/studio/projects`.
- Legacy Agent 2 workflow endpoints under `/studio/project` and `/studio/workflow` remain compatible.

## Current Endpoint Surface

- `POST /studio/projects`
- `GET /studio/projects/{project_name}`
- `GET /studio/projects/{project_name}/bible`
- `POST /studio/projects/{project_name}/bible`
- `POST /studio/projects/{project_name}/characters`
- `PUT /studio/projects/{project_name}/characters/{character_id}`
- `POST /studio/projects/{project_name}/episodes`
- `POST /studio/projects/{project_name}/minutes`
- `POST /studio/projects/{project_name}/panels`
- `GET /studio/projects/{project_name}/panels`
- `POST /studio/projects/{project_name}/continuity-warnings`
- `POST /studio/projects/{project_name}/approvals`
- `GET /studio/projects/{project_name}/export`
