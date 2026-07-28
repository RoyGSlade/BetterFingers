// Scenario registry. Each scenario module exports an array of scenarios
// matching the schema documented in docs/QA_VISUAL_WALKBOOK.md:
//
//   {
//     area: string,            // groups scenarios in the report + output dir
//     name: string,            // unique within area; also the screenshot filename
//     kind: 'standard' | 'negative-control',  // default 'standard'
//     description: string,     // one paragraph -- becomes the walkbook caption
//     backendState: object | () => object,    // stub routes for this scenario
//     navigate: (page) => Promise<void>,
//     expects: (page) => Promise<void>,        // playwright assertions
//     screenshots: [{ name: string, opts?: { mask?: string[] } }],
//   }
//
// A 'negative-control' scenario's `expects` is EXPECTED to throw (it asserts
// a truthfulness check against a deliberately-lying stub) -- the runner
// inverts pass/fail for these so the suite stays green while proving the
// harness actually catches lies. See run.mjs.

import { baselineScenarios } from './baseline.mjs';
import { voiceControlScenarios } from './voice-control.mjs';
import { privacyScenarios } from './privacy.mjs';
import { modelResourcesScenarios } from './model-resources.mjs';
import { doctorWarningsScenarios } from './doctor-warnings.mjs';
import { voiceCloningScenarios } from './voice-cloning.mjs';
import { messageRescueScenarios } from './message-rescue.mjs';
import { messageRescueDraftScenarios } from './message-rescue-draft.mjs';
import { textPlaygroundScenarios } from './text-playground.mjs';
import { draftsScenarios } from './drafts.mjs';
import { personaScenarios } from './personas.mjs';
// Signal Desk scenarios carry `ui: 'signal-desk'`; run.mjs filters by UI
// target, so these are skipped on a default run and vice versa.
import { signalDeskShellScenarios } from './signal-desk-shell.mjs';
import { signalDeskSectionScenarios } from './signal-desk-sections.mjs';
import { signalDeskTalkScenarios } from './signal-desk-talk.mjs';
import { onboardingScenarios } from './onboarding.mjs';
import { firstRunBannerScenarios } from './first-run-banner.mjs';
import { personaFlowScenarios } from './persona-flow.mjs';
import { contactsScenarios } from './contacts.mjs';
// Persona-learning scenarios carry `ui: 'signal-desk-prod'` (harness.mjs's
// third UI target, BF_QA_UI=signal-desk-prod): they drive the "Teach this
// persona from my edit" panel inside Studio (features/studioWorkspace.js),
// which reuses features/personaLearning.js's feature logic verbatim but
// binds it to distinct `sdTeach*` ids rather than personaLearning.js's own
// canonical `personaLearning*` ids -- see studioWorkspace.js's
// ID-COLLISION NOTE for why (reusing the canonical ids would let
// personaLearning.js's own import-time self-init IIFE double-wire the same
// elements with the wrong default hooks). Those `sdTeach*` ids exist only in
// the production Signal Desk composition root (signal-desk.html), never in
// index.html, hence the dedicated UI target instead of the default one.
import { personaLearningScenarios } from './persona-learning.mjs';
// The rest of the `ui: 'signal-desk-prod'` coverage (Wave 1, W1-G1). Both of
// these drive the production composition root through the real UI only --
// there is no window.__onboarding debug handle on signal-desk.html and none
// may be added, so onboarding-prod.mjs reaches first-run/completed state the
// way a real user does: the durable <BETTERFINGERS_DATA_DIR>/onboarding.json
// record and the legacy localStorage flag (see harness.mjs's
// enterFirstRunState/enterCompletedProfileState). Consequence: the
// onboarding-prod area REQUIRES BETTERFINGERS_DATA_DIR to be exported before
// the run, and those helpers refuse loudly rather than touch a real profile
// when it is not.
import { onboardingProdScenarios } from './onboarding-prod.mjs';
import { signalDeskProdSweepScenarios } from './signal-desk-prod-sweep.mjs';

export const scenarios = [
  ...baselineScenarios,
  ...voiceControlScenarios,
  ...privacyScenarios,
  ...modelResourcesScenarios,
  ...doctorWarningsScenarios,
  ...voiceCloningScenarios,
  ...messageRescueScenarios,
  ...messageRescueDraftScenarios,
  ...textPlaygroundScenarios,
  ...draftsScenarios,
  ...personaScenarios,
  ...signalDeskShellScenarios,
  ...signalDeskSectionScenarios,
  ...signalDeskTalkScenarios,
  ...onboardingScenarios,
  ...firstRunBannerScenarios,
  ...personaFlowScenarios,
  ...contactsScenarios,
  ...personaLearningScenarios,
  ...signalDeskProdSweepScenarios,
  // Ordered last among the prod-target scenarios as belt-and-braces, not as a
  // load-bearing requirement: the auto-dismiss sentinel these use is
  // single-shot (harness.mjs), so a first-run scenario cannot leave the shared
  // Electron window sitting behind a raised consent gate for whatever runs
  // next. Order here is a second line of defence, not the mechanism.
  ...onboardingProdScenarios,
];
