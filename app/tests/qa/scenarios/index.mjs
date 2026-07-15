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

export const scenarios = [...baselineScenarios];
