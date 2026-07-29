// Wave 11B (B-1): the Persona Foundry, on the PRODUCTION composition root.
//
// Run with:  BF_QA_UI=signal-desk-prod node tests/qa/run.mjs foundry
//
// WHY THIS FILE EXISTS, stated exactly, because the Wave 11 blockers list got
// the diagnosis wrong and the correction matters more than the fix:
//
//   docs/release/WAVE11_BLOCKERS.md B-1 said the Foundry's 23 unevidenced rows
//   would be closed by retargeting `app/tests/qa/scenarios/personas.mjs` to
//   `signal-desk-prod`. They would not have been. personas.mjs does not touch
//   the Foundry at all -- it exercises the MANUAL persona wizard (`#wizard*`)
//   and the Cleanup Preset select. Not one `#foundry*` id appears in it, so
//   retargeting it would have moved zero §3 rows while quietly breaking the
//   legacy rollback coverage it does provide. The Foundry simply had no QA on
//   either page. This file is that QA, written against production.
//
// WHAT IS AND IS NOT DRIFT. The Foundry markup is byte-for-byte the same ids in
// `signal-desk.html` as in `index.html` -- Signal Desk re-housed the dialog, it
// did not rename its controls. The only two Foundry-adjacent ids that differ:
//
//   `#openFoundryButton`  legacy: a real button in Settings -> AI Cleanup.
//                         production: a HIDDEN compatibility trigger
//                         (signal-desk.html's "Hidden compatibility triggers"
//                         block) that exists so personas.js's own
//                         initFoundry() binding still has something to bind.
//                         Clicking it directly is what the production shell
//                         does internally, but it is NOT the user's entry
//                         point, so this suite never clicks it.
//   `#sdOpenFoundryButton` production only: Studio's "✨ Build with AI". This
//                         is the real entry point -- studioWorkspace.js's
//                         handleOpenFoundryClick -> hooks.onOpenFoundryRequested
//                         -> personaFlow.openFoundry() (signalDeskApp.js:557),
//                         which opens the guided-flow chrome and THEN clicks
//                         the hidden trigger. Entering through Studio is the
//                         difference between proving the Foundry ships and
//                         proving a detached dialog can be forced open.
//
// That mapping is read out of the code named above, not matched by shape.
//
// DETERMINISM. Every Foundry route is stubbed with the exact shape
// `routes_foundry.py` returns (`{session_id, question, done}` /
// `{question, pushback, done}` / `{persona, warnings}` / `{cases}`), and the
// interview is driven by a scripted queue rather than by a model, so the same
// four screens render every run. `POST /personas` is stubbed as a CAPTURE, not
// a constant: the only way to tell "Save sent the approved stress verdicts"
// apart from "Save sent an empty card" is to look at the body that arrived.
// Per D-0021 that capture lives in the stub handler -- renderer traffic goes
// through the main-process proxy, so a page-level request listener would count
// zero forever and pass every assertion vacuously.

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';

const SESSION_ID = 'qa-foundry-session';

// The compiled persona `POST /personas/compile` returns. Its prompt is
// deliberately unlike anything the manual wizard's generatePromptPreview()
// produces, so asserting on it proves the COMPILED value reached the review
// screen rather than a regenerated one.
const COMPILED = {
  prompt: 'You are Vivian Glass. Answer in two sentences, never three, and never apologise.',
  temperature: 0.35,
  persona_card: {
    display_name: 'Vivian Glass',
    archetype: 'The unimpressed editor',
    temperament: ['dry', 'exact'],
    signature_moves: ['cuts the preamble'],
    favorite_phrases: ['To be precise'],
    forbidden: ['exclamation marks'],
    best_use_cases: ['code review replies'],
    reliability_score: 82,
  },
};

const COMPILE_WARNINGS = [
  'No sign-off configured, so the model may invent one.',
  'Two-sentence cap is stricter than the examples you gave.',
];

const STRESS_CASES = [
  { category: 'ambiguous_input', input: 'uh so the thing', output: 'Which thing do you mean?' },
  { category: 'hostile_input', input: 'this is garbage', output: 'To be precise: which part?' },
];

// --- captures ----------------------------------------------------------------

let personaWrites = [];
let interviewAnswers = [];

/**
 * The scripted interview. `POST /personas/interview/answer` pops the next entry
 * each time the renderer submits, which is what makes a four-screen walk
 * reproducible without a model: text question -> choice question -> examples
 * collection -> anti-example collection -> done.
 *
 * Shapes are `routes_foundry.py`'s: `foundry_next_prompt()` supplies `question`
 * (`kind` is 'text' | 'choice' | 'collection'; collections also carry `group`,
 * `count` and `minimum`, which is what personas.js renders as "(1/2 minimum)").
 *
 * The script repeats each collection group once at a higher count on purpose,
 * and that is not padding. #foundryCollectionList is re-rendered from the group
 * of the question that came BACK, so a script that switched from 'examples' to
 * 'anti_examples' on the very first Add would clear the list in the same tick
 * the example was added, and the assertion that the example was recorded could
 * never be written. Repeating the group is what a real interview does anyway --
 * it asks again until the minimum is met.
 */
function interviewScript() {
  return [
    {
      question: {
        kind: 'choice',
        prompt: 'How formal should this persona sound?',
        choices: ['very_formal', 'plain_spoken'],
      },
      pushback: null,
      done: false,
    },
    {
      question: {
        kind: 'collection',
        group: 'examples',
        prompt: 'Give me a line you would say and how you want it to come out.',
        count: 0,
        minimum: 2,
      },
      pushback: null,
      done: false,
    },
    {
      question: {
        kind: 'collection',
        group: 'examples',
        prompt: 'Give me a line you would say and how you want it to come out.',
        count: 1,
        minimum: 2,
      },
      pushback: null,
      done: false,
    },
    {
      question: {
        kind: 'collection',
        group: 'anti_examples',
        prompt: 'What would this persona never say?',
        count: 0,
        minimum: 1,
      },
      pushback: null,
      done: false,
    },
    {
      question: {
        kind: 'collection',
        group: 'anti_examples',
        prompt: 'What would this persona never say?',
        count: 1,
        minimum: 1,
      },
      pushback: null,
      done: false,
    },
    // The Continue that ends the interview. personas.js's collectionNext
    // handler sees `done` and calls foundryRunCompile() itself -- no separate
    // user action compiles, which is exactly what UI-03-026 claims.
    { question: null, pushback: null, done: true },
  ];
}

function foundryState(extra = {}) {
  return () => {
    personaWrites = [];
    interviewAnswers = [];
    const script = interviewScript();
    return {
      ...readyProfile(),
      'GET /personas': { 'True Janitor': { prompt: 'Clean it up.' } },
      'GET /personas-builtins': { builtins: ['True Janitor'] },
      'GET /contacts': { ok: true, contacts: [] },
      'GET /contacts/active': { ok: true, contact_id: '' },

      'POST /personas/interview/start': {
        session_id: SESSION_ID,
        question: { kind: 'text', prompt: 'Who is this persona for?' },
        done: false,
      },
      'POST /personas/interview/answer': (_req, { body }) => {
        interviewAnswers.push(body);
        return script.shift() ?? { question: null, pushback: null, done: true };
      },
      'POST /personas/compile': { persona: COMPILED, warnings: COMPILE_WARNINGS },
      'POST /personas/test-suite/run': { cases: STRESS_CASES },
      'POST /personas': (_req, { body }) => {
        personaWrites.push(body);
        return { ok: true, name: body?.name };
      },
      ...extra,
    };
  };
}

async function openFoundryFromStudio(page) {
  await page.click('.sd-nav__button[data-nav="studio"]');
  await expect(page.locator('#workspace-studio')).toBeVisible();
  // Studio's real entry point, not the hidden compatibility trigger.
  await page.click('#sdOpenFoundryButton');
  await expect(page.locator('#foundryOverlay')).toBeVisible();
}

// personas.js drives its four screens by toggling `.hidden` on the inner
// `#foundryScreen*` divs, while personaFlow.js's guided-flow chrome mirrors the
// same transition onto the outer `[data-flow-step]` sections. Asserting the
// INNER div is the honest check: it is the element the feature module itself
// controls, so a screen that advanced only in the chrome would still fail here.
async function expectScreen(page, screenId) {
  for (const id of [
    'foundryScreenInterview',
    'foundryScreenCollection',
    'foundryScreenStressTest',
    'foundryScreenReview',
  ]) {
    if (id === screenId) {
      await expect(page.locator(`#${id}`)).not.toHaveClass(/\bhidden\b/);
    } else {
      await expect(page.locator(`#${id}`)).toHaveClass(/\bhidden\b/);
    }
  }
}

// Walks the interview to the anti-example collection screen, leaving one
// example already added. Shared by the scenarios that need to be further along
// than the interview itself.
async function walkToAntiExamples(page) {
  await openFoundryFromStudio(page);

  await page.fill('#foundryAnswerInput', 'My code review replies.');
  await page.click('#foundrySubmitAnswerButton');

  await expect(page.locator('#foundryChoiceRow button')).toHaveCount(2);
  await page.click('#foundryChoiceRow button:has-text("plain spoken")');

  await expectScreen(page, 'foundryScreenCollection');
  // Two examples, because the scripted interview asks for two before it moves
  // the group on -- see interviewScript()'s comment.
  await page.fill('#foundryExampleRaw', 'this pr is fine i guess ship it');
  await page.fill('#foundryExampleDesired', 'This looks correct. Shipping.');
  await page.click('#foundryAddCollectionItemButton');
  await page.fill('#foundryExampleRaw', 'idk maybe we merge');
  await page.fill('#foundryExampleDesired', 'I suggest we merge.');
  await page.click('#foundryAddCollectionItemButton');

  await expect(page.locator('#foundryAntiExampleRow')).toBeVisible();
}

// Walks all the way to the review screen with one stress case approved.
async function walkToReview(page) {
  await walkToAntiExamples(page);
  await page.fill('#foundryAntiExampleText', 'Absolutely amazing work!!!');
  await page.click('#foundryAddCollectionItemButton');
  await page.click('#foundryCollectionNextButton');

  await expectScreen(page, 'foundryScreenStressTest');
  await page.click('#foundryRunStressTestButton');
  await expect(page.locator('#foundryStressCases .foundry-stress-case')).toHaveCount(2);
  await page
    .locator('#foundryStressCases .foundry-stress-case')
    .first()
    .locator('button:has-text("Approve")')
    .click();

  await page.click('#foundryStressContinueButton');
  await expectScreen(page, 'foundryScreenReview');
}

export const foundryProdScenarios = [
  {
    area: 'foundry',
    ui: 'signal-desk-prod',
    name: 'studio-opens-the-interview',
    kind: 'standard',
    description:
      'Studio\'s "Build with AI" opens the Persona Foundry on the production page and starts a real interview: '
      + 'the click goes through studioWorkspace.js\'s onOpenFoundryRequested hook into personaFlow.openFoundry(), '
      + 'which is what calls POST /personas/interview/start. The Interview screen (#foundryScreenInterview) is the '
      + 'one showing, the first question is appended to #foundryChatLog as a question bubble, and because that '
      + 'question is free-text the #foundryTextRow (#foundryAnswerInput + #foundrySubmitAnswerButton) is the input '
      + 'offered while #foundryChoiceRow stays hidden. Submitting swaps to a choice question, whose per-choice '
      + 'buttons are built from question.choices with underscores rendered as spaces, and the answer that was '
      + 'submitted is asserted on the request body -- a Foundry that rendered the next question without sending '
      + 'the previous answer would look identical on screen.',
    backendState: foundryState(),
    async navigate(page) {
      await openFoundryFromStudio(page);
    },
    async expects(page) {
      await expectScreen(page, 'foundryScreenInterview');
      await expect(page.locator('#foundryChatLog .foundry-bubble.question')).toHaveText([
        'Who is this persona for?',
      ]);
      await expect(page.locator('#foundryTextRow')).toBeVisible();
      await expect(page.locator('#foundryChoiceRow')).toBeHidden();
      await expect(page.locator('#foundryAnswerInput')).toBeVisible();
      await expect(page.locator('#foundrySubmitAnswerButton')).toBeVisible();

      // POST /personas/interview/answer (answerFoundryQuestion) carries the
      // session and the answer, and the reply drives the next screen.
      await page.fill('#foundryAnswerInput', 'My code review replies.');
      await page.click('#foundrySubmitAnswerButton');

      await expect(page.locator('#foundryChatLog .foundry-bubble.answer')).toHaveText([
        'My code review replies.',
      ]);
      await expect(page.locator('#foundryChoiceRow')).toBeVisible();
      await expect(page.locator('#foundryTextRow')).toBeHidden();
      await expect(page.locator('#foundryChoiceRow button')).toHaveText([
        'very formal',
        'plain spoken',
      ]);

      expect(interviewAnswers, 'exactly one answer submitted').toHaveLength(1);
      expect(interviewAnswers[0]).toEqual({
        session_id: SESSION_ID,
        answer: 'My code review replies.',
      });
    },
    screenshots: [{ name: 'studio-opens-the-interview' }],
  },
  {
    area: 'foundry',
    ui: 'signal-desk-prod',
    name: 'collection-screen-gathers-examples-and-anti-examples',
    kind: 'standard',
    description:
      'A collection question switches the Foundry to #foundryScreenCollection, where #foundryCollectionPrompt '
      + 'states the count against the minimum ("(0/2 minimum)") so a user knows how much more is wanted. The two '
      + 'collection modes are genuinely different surfaces and the screen swaps between them: an "examples" group '
      + 'shows the raw/desired pair (#foundryExampleRaw + #foundryExampleDesired) and hides '
      + '#foundryAntiExampleRow, and an "anti_examples" group does the reverse. #foundryAddCollectionItemButton '
      + 'refuses a half-filled pair through #foundryMessage rather than posting a broken example, and a complete '
      + 'pair lands in #foundryCollectionList as "raw → desired".',
    backendState: foundryState(),
    async navigate(page) {
      await openFoundryFromStudio(page);
      await page.fill('#foundryAnswerInput', 'My code review replies.');
      await page.click('#foundrySubmitAnswerButton');
      await page.click('#foundryChoiceRow button:has-text("plain spoken")');
    },
    async expects(page) {
      await expectScreen(page, 'foundryScreenCollection');
      await expect(page.locator('#foundryCollectionPrompt')).toHaveText(
        'Give me a line you would say and how you want it to come out. (0/2 minimum)',
      );
      await expect(page.locator('#foundryExamplePairRow')).toBeVisible();
      await expect(page.locator('#foundryAntiExampleRow')).toBeHidden();

      // Half-filled is refused locally, and nothing is posted.
      const answersBefore = interviewAnswers.length;
      await page.fill('#foundryExampleRaw', 'this pr is fine i guess ship it');
      await page.click('#foundryAddCollectionItemButton');
      await expect(page.locator('#foundryMessage')).toHaveText(
        'Give me both a raw input and the desired output.',
      );
      await expect(page.locator('#foundryMessage')).toHaveAttribute('data-tone', 'danger');
      expect(interviewAnswers.length, 'refusal posted nothing').toBe(answersBefore);

      // Complete pair: recorded, listed, and the inputs cleared for the next one.
      await page.fill('#foundryExampleDesired', 'This looks correct. Shipping.');
      await page.click('#foundryAddCollectionItemButton');
      await expect(page.locator('#foundryCollectionList li')).toHaveCount(1);
      await expect(page.locator('#foundryCollectionList li').first()).toHaveText(
        'this pr is fine i guess ship it → This looks correct. Shipping.',
      );
      await expect(page.locator('#foundryExampleRaw')).toHaveValue('');
      await expect(page.locator('#foundryExampleDesired')).toHaveValue('');
      await expect(page.locator('#foundryCollectionPrompt')).toHaveText(
        'Give me a line you would say and how you want it to come out. (1/2 minimum)',
      );
      expect(interviewAnswers[interviewAnswers.length - 1]).toEqual({
        session_id: SESSION_ID,
        answer: { raw: 'this pr is fine i guess ship it', desired: 'This looks correct. Shipping.' },
      });

      // The anti-example group is the other half of the same screen, and the
      // running list belongs to the CURRENT group -- switching groups shows the
      // anti-example list (empty), not a merged pile of both kinds.
      await page.fill('#foundryExampleRaw', 'idk maybe we merge');
      await page.fill('#foundryExampleDesired', 'I suggest we merge.');
      await page.click('#foundryAddCollectionItemButton');

      await expect(page.locator('#foundryAntiExampleRow')).toBeVisible();
      await expect(page.locator('#foundryExamplePairRow')).toBeHidden();
      await expect(page.locator('#foundryCollectionPrompt')).toHaveText(
        'What would this persona never say? (0/1 minimum)',
      );
      await expect(page.locator('#foundryCollectionList li')).toHaveCount(0);

      await page.fill('#foundryAntiExampleText', 'Absolutely amazing work!!!');
      await page.click('#foundryAddCollectionItemButton');
      await expect(page.locator('#foundryCollectionList li')).toHaveText([
        'Absolutely amazing work!!!',
      ]);
    },
    screenshots: [{ name: 'collection-screen-gathers-examples-and-anti-examples' }],
  },
  {
    area: 'foundry',
    ui: 'signal-desk-prod',
    name: 'continue-compiles-then-stress-test-runs',
    kind: 'standard',
    description:
      '#foundryCollectionNextButton is the end of the interview, and the compile that follows is AUTOMATIC: the '
      + 'answer that comes back marked done triggers POST /personas/compile with no further user action, and the '
      + 'Foundry moves itself to #foundryScreenStressTest. #foundryRunStressTestButton then posts '
      + 'POST /personas/test-suite/run and renders one card per returned case into #foundryStressCases -- each with '
      + 'its category, its input, its EDITABLE output, and its own Approve/Reject pair, which is the whole point of '
      + 'the screen: the verdicts are per case, not per suite. Approving one and rejecting another leaves two '
      + 'differently-marked cards rather than a single suite-level pass.',
    backendState: foundryState(),
    async navigate(page) {
      await walkToAntiExamples(page);
      await page.fill('#foundryAntiExampleText', 'Absolutely amazing work!!!');
      await page.click('#foundryAddCollectionItemButton');
    },
    async expects(page) {
      await page.click('#foundryCollectionNextButton');
      // Compile is not a user action -- reaching the stress screen IS the
      // evidence that the done-answer triggered compileFoundry.
      await expectScreen(page, 'foundryScreenStressTest');

      await expect(page.locator('#foundryStressCases .foundry-stress-case')).toHaveCount(0);
      await page.click('#foundryRunStressTestButton');

      const cases = page.locator('#foundryStressCases .foundry-stress-case');
      await expect(cases).toHaveCount(2);
      await expect(cases.locator('.foundry-stress-case-category')).toHaveText([
        'ambiguous input',
        'hostile input',
      ]);
      await expect(cases.first().locator('textarea')).toHaveValue('Which thing do you mean?');
      await expect(cases.first()).toHaveAttribute('data-verdict', 'pending');

      await cases.first().locator('button:has-text("Approve")').click();
      await cases.nth(1).locator('button:has-text("Reject")').click();
      await expect(cases.first()).toHaveAttribute('data-verdict', 'approved');
      await expect(cases.nth(1)).toHaveAttribute('data-verdict', 'rejected');

      await expect(page.locator('#foundryStressContinueButton')).toBeVisible();
    },
    screenshots: [{ name: 'continue-compiles-then-stress-test-runs' }],
  },
  {
    area: 'foundry',
    ui: 'signal-desk-prod',
    name: 'review-card-and-save',
    kind: 'standard',
    description:
      '#foundryStressContinueButton opens #foundryScreenReview, which is where the compile result becomes '
      + 'reviewable: #foundryCharacterCard renders the persona card (archetype, temperament, signature moves, '
      + 'favourite phrases, forbidden, best use cases and the reliability score), #foundryPersonaName is '
      + 'pre-filled from the card\'s display name, #foundryCompiledPrompt shows the compiled prompt read-only, '
      + 'and #foundryCompileWarnings surfaces the compile warnings in a warning tone instead of dropping them. '
      + 'Save is guarded: clearing the name refuses through #foundryMessage and posts nothing. With a name, '
      + '#foundrySaveButton posts to POST /personas and the body is asserted -- the compiled prompt, and a '
      + 'persona_card whose eval_cases carry the stress verdicts the user actually gave. A save that dropped the '
      + 'verdicts, or that sent a regenerated prompt, renders exactly the same and is caught only here.',
    backendState: foundryState(),
    async navigate(page) {
      await walkToReview(page);
    },
    async expects(page) {
      await expect(page.locator('#foundryCharacterCard h3')).toHaveText('Vivian Glass');
      await expect(page.locator('#foundryCharacterCard .foundry-archetype')).toHaveText(
        'The unimpressed editor',
      );
      await expect(page.locator('#foundryCharacterCard dt')).toHaveText([
        'Temperament',
        'Signature moves',
        'Favorite phrases',
        'Forbidden',
        'Best use cases',
      ]);
      await expect(page.locator('#foundryCharacterCard dd').first()).toHaveText('dry, exact');
      await expect(page.locator('#foundryCharacterCard .foundry-reliability-score')).toHaveText(
        'Reliability: 82/100',
      );

      await expect(page.locator('#foundryPersonaName')).toHaveValue('Vivian Glass');
      await expect(page.locator('#foundryCompiledPrompt')).toHaveValue(COMPILED.prompt);
      await expect(page.locator('#foundryCompiledPrompt')).toHaveAttribute('readonly', '');
      await expect(page.locator('#foundryCompileWarnings')).toHaveText(COMPILE_WARNINGS.join(' '));
      await expect(page.locator('#foundryCompileWarnings')).toHaveAttribute('data-tone', 'warning');

      // Nameless save is refused, and refused locally.
      await page.fill('#foundryPersonaName', '');
      await page.click('#foundrySaveButton');
      await expect(page.locator('#foundryMessage')).toHaveText('Give this persona a name first.');
      expect(personaWrites, 'nameless save posted nothing').toHaveLength(0);

      await page.fill('#foundryPersonaName', 'Vivian Glass');
      await page.click('#foundrySaveButton');

      await expect(page.locator('#foundryOverlay')).toBeHidden();
      expect(personaWrites, 'exactly one save').toHaveLength(1);
      const saved = personaWrites[0];
      expect(saved.name).toBe('Vivian Glass');
      expect(saved.prompt).toBe(COMPILED.prompt);
      expect(saved.persona_card.display_name).toBe('Vivian Glass');
      expect(saved.persona_card.eval_cases).toEqual([
        {
          category: 'ambiguous_input',
          input: 'uh so the thing',
          output: 'Which thing do you mean?',
          verdict: 'approved',
        },
      ]);
    },
    screenshots: [{ name: 'review-card-and-save' }],
  },
  {
    area: 'foundry',
    ui: 'signal-desk-prod',
    name: 'close-abandons-without-saving',
    kind: 'standard',
    description:
      '#foundryCloseButton (×) abandons an in-progress Foundry session: the dialog goes away, nothing is posted '
      + 'to POST /personas, and re-entering through Studio starts a genuinely new interview rather than resuming '
      + 'the half-finished one -- #foundryChatLog holds exactly the first question again, not the accumulated '
      + 'transcript of the abandoned run. foundryOpen() clearing its own state is invisible in a screenshot and is '
      + 'the difference between "start over" and "silently continue editing a persona you walked away from".',
    backendState: foundryState(),
    async navigate(page) {
      await walkToAntiExamples(page);
    },
    async expects(page) {
      await page.click('#foundryCloseButton');
      await expect(page.locator('#foundryOverlay')).toBeHidden();
      expect(personaWrites, 'abandoning saves nothing').toHaveLength(0);

      await page.click('#sdOpenFoundryButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
      await expectScreen(page, 'foundryScreenInterview');
      await expect(page.locator('#foundryChatLog .foundry-bubble')).toHaveText([
        'Who is this persona for?',
      ]);
      await expect(page.locator('#foundryCollectionList li')).toHaveCount(0);
    },
    screenshots: [{ name: 'close-abandons-without-saving' }],
  },
];
