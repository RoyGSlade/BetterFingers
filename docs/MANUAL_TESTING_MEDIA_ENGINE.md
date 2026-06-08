# Manual Testing Guide: Media Dispatcher & Studio Features

This document outlines the manual verification steps for the recently implemented Media Dispatcher milestones (P1, P2, P2.5) and the foundational UI/Networking updates.

---

## 1. Resumable Background Downloads
**Objective:** Verify that large models (GGUFs and Diffusers snapshots) download in the background, survive interruptions, and do not spawn duplicate threads.

*   **Step 1:** Go to the Models or Settings tab and initiate a download for a large model (e.g., Gemma 12B or Animagine XL 4.0).
*   **Step 2:** Ensure the UI remains responsive and the download progress polls correctly.
*   **Step 3:** Click the download button a second time while it is already downloading. 
    *   *Expected:* The system should log that a download is already in progress and reuse the active job without crashing or duplicating.
*   **Step 4:** Close the application entirely when the download is roughly 50% complete.
*   **Step 5:** Reopen the application and click download for the same model.
    *   *Expected:* The console logs should indicate "Resuming download from X MB" and complete the remaining file size atomically, resulting in a healthy model state.

## 2. Studio Settings & Model Roles
**Objective:** Ensure the new taxonomic role UI accurately persists and dictates Studio constraints.

*   **Step 1:** Navigate to Settings -> Studio Media Engine.
*   **Step 2:** Toggle the `Resource Profile` between *Background VRAM Saver* and *Speedy Pipeline*. Adjust the `VRAM Budget Cap`.
*   **Step 3:** Assign models to the `Dispatcher Model`, `Smart Writer Model`, and select `Diffusers` as the Image Backend.
*   **Step 4:** Restart the app.
    *   *Expected:* All settings and model selections should persist perfectly.
*   **Step 5:** Check the Dashboard/Hardware panel.
    *   *Expected:* The UI should honestly reflect whether the selected backends are "loaded", "offline", or "not configured."

## 3. Visual Prompt Compiler & Stable Continuity (P1)
**Objective:** Verify that the LLM generates visual *specs*, and the deterministic code compiles the actual prompts with locked seeds.

*   **Step 1:** Create a new Studio Project with a basic 2-character story. Let the Showrunner generate the bibles and the Scriptwriter generate the scene visual specs.
*   **Step 2:** Trigger image rendering.
*   **Step 3:** Navigate to the project's folder in the file system and open `renders/jobs/<id>.prompt.json` for two different scenes featuring the same character.
    *   *Expected:* The compiled `positive_prompt` should include the character's core visual traits pulled from the character bible.
    *   *Expected:* The `seed` integer should be identical across both scenes for that specific character, proving the stable continuity lock is working.

## 4. In-Process Diffusers Rendering & VRAM Reclaim (P2 & P2.5)
**Objective:** Ensure the local SDXL/Flux pipeline successfully generates an image without an external app, and honors the VRAM Saver unloads.

*   **Step 1:** Ensure `diffusers` and `accelerate` are installed in the `.venv`.
*   **Step 2:** Download the `Animagine XL 4.0` snapshot via the Studio UI (or confirm it's installed).
*   **Step 3:** Run the cinematic rendering pipeline for a 1-2 panel scene.
*   **Step 4:** Monitor your GPU VRAM externally (using `nvidia-smi` or Windows Task Manager).
    *   *Expected 1:* VRAM usage should spike (by ~6-8GB) as the pipeline loads and renders.
    *   *Expected 2:* A valid `768x768` (or configured resolution) PNG should be saved to the project's image assets folder.
    *   *Expected 3:* Immediately after the render completes, VRAM usage must drop back to baseline (as the pipeline is deleted and `torch.cuda.empty_cache()` is called).

## 5. Automated Test Suite Validation
**Objective:** Ensure the deterministic logic remains perfectly green.

*   **Step 1:** In the terminal, run: `.venv/bin/python -m pytest tests/test_studio_prompt_compiler.py tests/test_studio_image_backend.py tests/test_studio_render.py`
    *   *Expected:* All tests pass without warnings.
*   **Step 2:** Run the full studio suite: `.venv/bin/python -m pytest tests/ -k "studio"`
    *   *Expected:* Suite passes (excluding any known historical failures like the GEST endpoint test).
