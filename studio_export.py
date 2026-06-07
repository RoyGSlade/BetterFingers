"""Deterministic export service for Source Arcanum Studio.

Turns a finished Studio project (premise, world, characters, panels, dialogue,
continuity warnings) into a portable, human-readable production package:

    exports/<timestamp>/
        project.json            full structured project state
        bibles/
            series_bible.md     premise, theme, mode, logline
            world_bible.md      setting, aesthetic, rules, locations
            character_bible.md  every character with role/desc/voice
            style_bible.md      visual style + per-panel image prompts
        script.md               panel-by-panel screenplay (visual + dialogue)
        subtitles.srt           timed captions from the dialogue + durations
        reel.html               self-contained scrolling comic-reel preview
        export_report.md        models used, counts, warnings, settings
    <Project>_reel.zip          the whole folder zipped for sharing

Everything is deterministic code (no agents): file creation, formatting, timing,
and packaging per the spec's "use deterministic code for export" rule. The reel.html
is the MVP "preview reel" — it renders locally in any browser with no dependencies.
"""

import os
import re
import json
import html
import zipfile
import logging
from datetime import datetime, timezone

import studio_memory as memory

logger = logging.getLogger("studio_export")


def _as_dict(value):
    """Coerce a metadata field that may be a JSON string, dict, or None into a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {}


def _ordered_panels(payload):
    """Return panels in narrative order with their dialogue + metadata attached."""
    minute_order = {m["id"]: m.get("minute_number", 0) for m in payload.get("minutes", [])}
    page_order = {p["id"]: p.get("page_number", 0) for p in payload.get("pages", [])}
    dialogue_by_panel = {}
    for line in payload.get("dialogue_lines", []):
        dialogue_by_panel.setdefault(line["panel_id"], []).append(line)

    panels = []
    for panel in payload.get("panels", []):
        meta = _as_dict(panel.get("metadata"))
        panels.append({
            "panel_number": panel.get("panel_number", 0),
            "page_number": page_order.get(panel.get("page_id"), 0),
            "minute_number": minute_order.get(panel.get("minute_id"), 0),
            "visual_description": panel.get("visual_description", ""),
            "style_prompt": panel.get("style_prompt") or meta.get("style_prompt", ""),
            "meta": meta,
            "dialogue": dialogue_by_panel.get(panel.get("id"), []),
        })
    panels.sort(key=lambda p: (p["page_number"], p["minute_number"], p["panel_number"]))
    return panels


def _h(text):
    return html.escape(str(text or ""))


def _join(lines):
    """Join markdown lines, coercing any None/non-str entries to safe strings."""
    return "\n".join("" if x is None else str(x) for x in lines) + "\n"


# --- Markdown bible builders -------------------------------------------------

def _series_bible_md(payload):
    bible = payload.get("bible", {})
    premise = bible.get("premise", {}) if isinstance(bible, dict) else {}
    project = payload.get("project", {})
    lines = [
        f"# Series Bible — {premise.get('title', project.get('name', 'Untitled'))}",
        "",
        f"- **Mode:** {bible.get('mode', 'seed')}",
        f"- **Theme:** {premise.get('theme', '—')}",
        "",
        "## Logline",
        premise.get("premise", "_No premise recorded._"),
        "",
        "## Canon Events",
    ]
    events = payload.get("canon_events", [])
    if events:
        for ev in events:
            lines.append(f"- `{ev.get('time_index', '—')}` {ev.get('description', '')}")
    else:
        lines.append("_No canon events recorded._")
    return _join(lines)


def _world_bible_md(payload):
    bible = payload.get("bible", {})
    world = bible.get("world", {}) if isinstance(bible, dict) else {}
    lines = [
        "# World Bible",
        "",
        "## Setting",
        world.get("setting", "_No setting recorded._"),
        "",
        "## Aesthetic",
        world.get("aesthetic", "_No aesthetic recorded._"),
        "",
        "## World Rules",
    ]
    for rule in world.get("rules", []) or ["_No rules recorded._"]:
        lines.append(f"- {rule}")
    lines += ["", "## Locations"]
    locations = payload.get("locations", [])
    if locations:
        for loc in locations:
            lines.append(f"### {loc.get('name', 'Unnamed')}")
            lines.append(loc.get("description", ""))
            lines.append("")
    else:
        lines.append("_No locations recorded._")
    return _join(lines)


def _character_bible_md(payload):
    lines = ["# Character Bible", ""]
    characters = payload.get("characters", [])
    if not characters:
        return "# Character Bible\n\n_No characters recorded._\n"
    for ch in characters:
        meta = _as_dict(ch.get("metadata"))
        lines.append(f"## {ch.get('name', 'Unnamed')}")
        lines.append(f"- **Role:** {ch.get('role', '—')}")
        lines.append(f"- **Archetype:** {ch.get('archetype', '—')}")
        if meta.get("skin_id"):
            lines.append(f"- **Visual anchor (skin):** `{meta['skin_id']}`")
        lines.append("")
        lines.append(ch.get("description", ""))
        lines.append("")
    return _join(lines)


def _style_bible_md(payload, panels):
    bible = payload.get("bible", {})
    world = bible.get("world", {}) if isinstance(bible, dict) else {}
    lines = [
        "# Style Bible",
        "",
        "## Visual Tone",
        world.get("aesthetic", "_No aesthetic recorded._"),
        "",
        "## Per-Panel Image Prompts",
        "",
        "| Page/Panel | Camera | Image Prompt | Negative Prompt |",
        "| - | ------ | ------------ | --------------- |",
    ]
    for p in panels:
        meta = p["meta"]
        prompt = meta.get("image_prompt") or f"{p['visual_description']}. {p['style_prompt']}"
        neg = meta.get("negative_prompt", "")
        cam = meta.get("camera", "")
        prompt = prompt.replace("|", "/").replace("\n", " ")
        neg = neg.replace("|", "/")
        panel_label = f"P{p['page_number']}-{p['panel_number']}" if p.get("page_number") else str(p["panel_number"])
        lines.append(f"| {panel_label} | {cam} | {prompt} | {neg} |")
    return _join(lines)


def _script_md(payload, panels):
    project = payload.get("project", {})
    bible = payload.get("bible", {})
    premise = bible.get("premise", {}) if isinstance(bible, dict) else {}
    lines = [
        f"# {premise.get('title', project.get('name', 'Untitled'))} — Comic Reel Script",
        "",
        f"_{premise.get('premise', '')}_",
        "",
        "---",
        "",
    ]
    for p in panels:
        meta = p["meta"]
        cam = meta.get("camera", "")
        dur = meta.get("duration_seconds", 5)
        page_label = f"Page {p['page_number']} · " if p.get("page_number") else ""
        lines.append(f"## {page_label}Panel {p['panel_number']}  ·  {cam}  ·  {dur}s")
        lines.append(f"**Visual:** {p['visual_description']}")
        visible = meta.get("visible_characters") or []
        if visible:
            lines.append(f"**On screen:** {', '.join(visible)}")
        lines.append("")
        for line in p["dialogue"]:
            speaker = line.get("speaker", "Narrator")
            text = line.get("text", "")
            if speaker.lower() == "narrator":
                lines.append(f"> _{text}_")
            else:
                lines.append(f"**{speaker.upper()}:** {text}")
        lines.append("")
    return _join(lines)


# --- Subtitles ---------------------------------------------------------------

def _srt_timestamp(seconds):
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _subtitles_srt(panels):
    blocks = []
    t = 0.0
    idx = 1
    for p in panels:
        dur = float(p["meta"].get("duration_seconds", 5) or 5)
        lines = p["dialogue"] or [{"speaker": "Narrator", "text": p["visual_description"]}]
        slice_dur = dur / max(1, len(lines))
        for line in lines:
            start, end = t, t + slice_dur
            speaker = line.get("speaker", "Narrator")
            text = line.get("text", "")
            caption = text if speaker.lower() == "narrator" else f"{speaker}: {text}"
            blocks.append(f"{idx}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{caption}\n")
            idx += 1
            t = end
    return "\n".join(blocks)


# --- Reel HTML preview -------------------------------------------------------

def _reel_html(payload, panels):
    bible = payload.get("bible", {})
    premise = bible.get("premise", {}) if isinstance(bible, dict) else {}
    world = bible.get("world", {}) if isinstance(bible, dict) else {}
    title = premise.get("title", payload.get("project", {}).get("name", "Comic Reel"))

    panel_html = []
    for p in panels:
        meta = p["meta"]
        cam = _h(meta.get("camera", ""))
        dur = _h(meta.get("duration_seconds", 5))
        bubbles = []
        for line in p["dialogue"]:
            speaker = line.get("speaker", "Narrator")
            cls = "narration" if speaker.lower() == "narrator" else "bubble"
            who = "" if speaker.lower() == "narrator" else f'<span class="who">{_h(speaker)}</span>'
            bubbles.append(f'<div class="{cls}">{who}<span class="say">{_h(line.get("text", ""))}</span></div>')
        panel_html.append(f"""
      <article class="panel">
        <div class="art" data-cam="{cam}">
          <div class="art-meta"><span class="num">PANEL {p['panel_number']}</span><span class="cam">{cam} · {dur}s</span></div>
          <p class="vis">{_h(p['visual_description'])}</p>
        </div>
        <div class="script">{''.join(bubbles) or '<div class="narration"><span class="say">…</span></div>'}</div>
      </article>""")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_h(title)} — Comic Reel</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0b0c10; color:#e8e6e3; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
  header {{ position:sticky; top:0; z-index:5; padding:20px 24px; background:linear-gradient(180deg,#0b0c10 70%,transparent); border-bottom:1px solid #1c1f26; }}
  header h1 {{ margin:0 0 4px; font-size:22px; letter-spacing:.3px; }}
  header p {{ margin:0; color:#9aa0ab; font-size:13px; max-width:70ch; }}
  main {{ max-width:760px; margin:0 auto; padding:28px 18px 80px; }}
  .panel {{ margin:0 0 40px; opacity:0; transform:translateY(24px); animation:rise .6s ease forwards; }}
  @keyframes rise {{ to {{ opacity:1; transform:none; }} }}
  .art {{ position:relative; aspect-ratio:16/10; border-radius:14px; overflow:hidden;
    background:
      radial-gradient(120% 80% at 30% 10%, rgba(120,140,200,.18), transparent 60%),
      repeating-linear-gradient(135deg, #14161c 0 22px, #11131a 22px 44px);
    border:1px solid #232732; box-shadow:0 10px 40px rgba(0,0,0,.5); display:flex; flex-direction:column; justify-content:flex-end; }}
  .art-meta {{ position:absolute; top:0; left:0; right:0; display:flex; justify-content:space-between;
    padding:10px 14px; font-size:11px; letter-spacing:1.5px; color:#8b93a3; text-transform:uppercase; }}
  .num {{ color:#cbd2e0; font-weight:700; }}
  .vis {{ margin:0; padding:16px 18px; font-size:15px; line-height:1.45; color:#d7dbe3;
    background:linear-gradient(0deg, rgba(8,9,12,.92), transparent); }}
  .script {{ padding:12px 6px 0; }}
  .bubble, .narration {{ margin:8px 0; padding:12px 16px; border-radius:12px; line-height:1.5; }}
  .bubble {{ background:#191c24; border:1px solid #262b36; }}
  .narration {{ background:transparent; color:#aab1bf; font-style:italic; border-left:3px solid #3a4150; border-radius:4px; }}
  .who {{ display:block; font-size:11px; letter-spacing:1.5px; text-transform:uppercase; color:#7f9cff; margin-bottom:3px; font-weight:700; }}
  footer {{ text-align:center; color:#5b616d; font-size:12px; padding:30px; }}
</style></head>
<body>
  <header>
    <h1>{_h(title)}</h1>
    <p>{_h(premise.get('premise', ''))}</p>
    <p style="margin-top:6px;color:#6f7e8c">{_h(world.get('aesthetic', ''))}</p>
  </header>
  <main>{''.join(panel_html)}</main>
  <footer>Source Arcanum Studio · local comic-reel preview · {len(panels)} panels</footer>
</body></html>"""


def _export_report_md(payload, panels, model_status=None):
    project = payload.get("project", {})
    warnings = payload.get("continuity_warnings", [])
    chars = payload.get("characters", [])
    total_seconds = sum(float(p["meta"].get("duration_seconds", 5) or 5) for p in panels)
    lines = [
        "# Export Report",
        "",
        f"- **Project:** {project.get('name', '—')}",
        f"- **Exported:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Pages:** {len(payload.get('pages', []))}",
        f"- **Panels:** {len(panels)}",
        f"- **Characters:** {len(chars)}",
        f"- **Approx. runtime:** {total_seconds:.0f}s",
        f"- **Continuity warnings:** {len(warnings)}",
        "",
        "## Model / Generation",
    ]
    ms = model_status or {}
    lines.append(f"- **LLM attempted:** {ms.get('llm_attempted', 'unknown')}")
    lines.append(f"- **LLM ready:** {ms.get('llm_ready', 'unknown')}")
    lines.append(f"- **Used procedural fallback:** {ms.get('used_fallback', 'unknown')}")
    lines.append(f"- **Model id:** {ms.get('model_id') or '—'}")
    lines += ["", "## Continuity Warnings"]
    if warnings:
        for w in warnings:
            lines.append(f"- **[{w.get('severity', 'low')}]** ({w.get('target_type')} {w.get('target_id')}) {w.get('message', '')}")
    else:
        lines.append("_None flagged._")
    lines += [
        "",
        "## Copyright / IP",
        "- Generated locally. Encourage original characters and worlds.",
        "- Review any resemblance to named, trademarked, or copyrighted IP before public release.",
    ]
    return _join(lines)


# --- Orchestration -----------------------------------------------------------

def export_project(project_name, project_id=None, model_status=None):
    """Build the full export package on disk and return a manifest of written files."""
    if project_id is None:
        try:
            project = memory.get_project_by_name(project_name)
        except Exception as e:
            raise ValueError(f"Project not found: {project_name} ({e})")
        if not project:
            raise ValueError(f"Project not found: {project_name}")
        project_id = project["id"]

    payload = memory.export_project_json(project_name, project_id)
    if not payload:
        raise ValueError(f"Project has no exportable data: {project_name}")

    panels = _ordered_panels(payload)

    project_dir = memory.get_project_dir(project_name)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(str(project_dir), "exports", stamp)
    bibles_dir = os.path.join(out_dir, "bibles")
    os.makedirs(bibles_dir, exist_ok=True)

    files = {
        "project.json": json.dumps(payload, indent=2, default=str),
        os.path.join("bibles", "series_bible.md"): _series_bible_md(payload),
        os.path.join("bibles", "world_bible.md"): _world_bible_md(payload),
        os.path.join("bibles", "character_bible.md"): _character_bible_md(payload),
        os.path.join("bibles", "style_bible.md"): _style_bible_md(payload, panels),
        "script.md": _script_md(payload, panels),
        "subtitles.srt": _subtitles_srt(panels),
        "reel.html": _reel_html(payload, panels),
        "export_report.md": _export_report_md(payload, panels, model_status),
    }

    written = []
    for rel, content in files.items():
        path = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        written.append(path)

    # Zip the whole export folder for easy sharing.
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", project_name)[:60] or "reel"
    zip_path = os.path.join(str(project_dir), "exports", f"{safe}_{stamp}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in written:
            zf.write(path, os.path.relpath(path, out_dir))

    logger.info("Studio export complete: %s (%d files)", out_dir, len(written))
    return {
        "ok": True,
        "project_name": project_name,
        "project_id": project_id,
        "export_dir": out_dir,
        "zip_path": zip_path,
        "reel_html": os.path.join(out_dir, "reel.html"),
        "files": [os.path.relpath(p, out_dir) for p in written],
        "panel_count": len(panels),
    }
