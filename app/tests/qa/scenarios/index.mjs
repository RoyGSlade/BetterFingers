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
// NOT imported on purpose: ./persona-learning.mjs (3 scenarios, area
// 'persona-learning'). They drive #personaLearningSection /
// #personaLearningConfirmButton / #personaLearningPersonaLabel, none of which
// exist in index.html -- those ids live only in features/personaLearning.js
// and features/studioWorkspace.js, i.e. the Signal Desk STUDIO workspace,
// which is not in electron.vite.config.js's build inputs and therefore never
// ships. Verified 2026-07-25: wiring them in yields 0/3, failing on
// "#personaLearningSection ... element(s) not found" -- a true report that the
// feature is unreachable, not a scenario bug. Registering them today would
// make `npm run qa:screens` permanently red and train people to ignore it,
// which is the exact failure the run.mjs exit-code fix just removed. Re-enable
// this import in the same change that mounts the Studio workspace in the
// shipping renderer.

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
];
