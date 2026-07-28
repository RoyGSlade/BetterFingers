// Persona creation on the guided-flow shell (stage 13 §4c,
// docs/ui/SIGNAL_DESK_GUIDED_FLOWS.md).
//
// One dialog, three entry paths, one save. Studio's "+ New Persona" opens the
// manual wizard at Goal & role (-> Tone -> Rules -> Review & save); "Build with
// AI" opens the Persona Foundry's model-led interview (Interview -> Examples ->
// Stress test -> Review & save); Wave 5's Edit opens the SAME wizard path at
// Review & save with the persona already loaded. All three end at the same
// POST /personas.
//
// The point of routing Edit through here rather than giving it its own editor
// is that a second editor is a second save path, and two things that can write
// a persona is how a persona gets written twice with different fields. Edit
// therefore borrows the wizard rather than reimplementing it, and does not save
// anything itself.
//
// WHAT THIS DOES NOT DO, and why: it does not take over stepping. The wizard
// advances from its own Back/Next plus a jump to step 4 when the model drafts a
// persona; the Foundry advances on backend results and per-screen Continue
// buttons. Porting either onto the shell's footer would mean rewriting ~300
// lines of validation and prompt regeneration that has no unit coverage to land
// on -- the big-bang rewrite rule 7 exists to prevent. The shell supplies the
// dialog chrome (overlay, focus trap and return, Escape, title, progress) and
// FOLLOWS the builders via the observers personas.js now exposes.
//
// The design doc originally said both paths would converge on the Foundry's
// review screen. They do not, and should not: the Foundry's review renders a
// compiled character card, while the wizard's step 4 carries the editable
// prompt, advanced knobs, lint, sample test and few-shot editor. Collapsing
// them would delete real capability from one side. What genuinely converges is
// the dialog, the entry points and the save call.

import { createGuidedFlow } from './guidedFlow.js';
import { setFoundryScreenObserver, setWizardStepObserver } from './personas.js';

/** Element keys createPersonasFeature expects; each equals its DOM id. */
export const WIZARD_ELEMENT_IDS = [
  'wizardStepProgress', 'wizardPrevButton', 'wizardNextButton', 'wizardDeleteButton', 'wizardMessage',
  'wizardRole', 'wizardCustomRole', 'wizardCustomRoleLabel', 'wizardTone', 'wizardCustomTone', 'wizardCustomToneLabel',
  'wizardRuleLength', 'wizardRuleCommands', 'wizardRuleNoPreamble', 'wizardRuleSanitize',
  'wizardPersonaName', 'wizardPromptPreview', 'wizardRegeneratePromptButton',
  'wizardTemperature', 'wizardModelHint', 'wizardFormatCaps', 'wizardFormatPunctuation', 'wizardFormatSignoff',
  'wizardOutputPolicy', 'wizardSafetyMode', 'wizardMaxCompletionTokens', 'wizardChunkSize',
  'wizardFewShotList', 'wizardAddFewShotButton', 'wizardLintButton', 'wizardLintWarnings',
  'wizardTestSample', 'wizardTestButton', 'wizardTestResult',
  'wizardRefinePromptButton', 'wizardRefineStatus', 'wizardRefinePanel',
  'wizardRefineUnderstood', 'wizardRefineAmbiguities', 'wizardRefinedPrompt',
  'wizardApplyRefinedButton', 'wizardDismissRefinedButton',
  'wizardRefinePromptBlock', 'wizardRefineActions',
  'wizardDescribeInput', 'wizardDescribeButton', 'wizardDescribeStatus', 'wizardAdvanced',
  // Stage 10 trait sliders + their band labels. Listed explicitly rather than
  // generated so adding an axis is a reviewed edit in one place.
  'wizardTraitWarmth', 'wizardTraitWarmthBand',
  'wizardTraitDirectness', 'wizardTraitDirectnessBand',
  'wizardTraitDetail', 'wizardTraitDetailBand',
  'wizardTraitFormality', 'wizardTraitFormalityBand',
  'wizardTraitConfidence', 'wizardTraitConfidenceBand',
];

export function collectPersonaWizardElements(doc = globalThis.document) {
  const elements = {};
  for (const id of WIZARD_ELEMENT_IDS) {
    elements[id] = doc.getElementById(id);
  }
  return elements;
}

/** Manual path: form-led, four steps ending in Review & save. */
export const WIZARD_STEPS = [
  { id: 'wizard1', title: 'Goal & role' },
  { id: 'wizard2', title: 'Tone' },
  { id: 'wizard3', title: 'Rules' },
  { id: 'wizard4', title: 'Review & save' },
];

/** Foundry path: model-led, four screens ending in Review & save. */
export const FOUNDRY_STEPS = [
  { id: 'interview', title: 'Interview' },
  { id: 'collection', title: 'Examples' },
  { id: 'stressTest', title: 'Stress test' },
  { id: 'review', title: 'Review & save' },
];

/** Foundry screen name -> flow step id. Identical today; named so it stays honest. */
export function foundryStepIdFor(screen) {
  return FOUNDRY_STEPS.some((s) => s.id === screen) ? screen : null;
}

/** Wizard step number (1-4) -> flow step id. */
export function wizardStepIdFor(stepNum) {
  const index = Number(stepNum) - 1;
  return WIZARD_STEPS[index]?.id ?? null;
}

/**
 * @param {object} opts
 * @param {HTMLElement} opts.root  the #foundryOverlay dialog
 * @param {HTMLElement} [opts.footer]  path-specific footer (hidden on the Foundry path)
 * @param {HTMLElement} [opts.foundryTrigger]  the hidden #openFoundryButton personas.js binds
 * @param {Function} [opts.observeWizardStep]  injectable registration; the real one is
 *   module-level state in personas.js, so a test that wants to drive the following has to
 *   be handed the callback rather than reach for a private
 * @param {Function} [opts.observeFoundryScreen]  same
 * @param {Function} [opts.openPersonaForEdit]  personas.js's openPersonaForEdit;
 *   loads a saved persona into the wizard at Review & save. Injected rather
 *   than imported because it is per-instance closure state inside
 *   createPersonasFeature, not a module-level function.
 */
export function createPersonaFlow({
  root,
  footer,
  foundryTrigger,
  observeWizardStep = setWizardStepObserver,
  observeFoundryScreen = setFoundryScreenObserver,
  openPersonaForEdit,
  doc = globalThis.document,
} = {}) {
  // Two flows over one root. They share the markup and differ only in which
  // four sections they address, which is why the shell resolves steps by id
  // rather than by position.
  const wizardFlow = createGuidedFlow({ root, steps: WIZARD_STEPS, doc });
  const foundryFlow = createGuidedFlow({ root, steps: FOUNDRY_STEPS, doc });

  let active = null;

  function setFooter(path) {
    if (!footer) return;
    // The Foundry's advances are all Continue buttons inside the screen that
    // produced the thing being continued from; a second Next in the footer
    // would be a control with nothing to do.
    footer.hidden = path !== 'wizard';
    footer.dataset.personaFooter = path;
  }

  // personas.js toggles `.hidden` on the root (foundryOpen/foundryClose) while
  // the shell uses the `hidden` property. Both have to agree or the dialog is
  // half-open: visible to one mechanism and not the other.
  function showRoot() {
    root?.classList?.remove?.('hidden');
  }

  function hideRoot() {
    root?.classList?.add?.('hidden');
  }

  function openWizard() {
    active = 'wizard';
    setFooter('wizard');
    showRoot();
    wizardFlow.open();
    // Whatever step the wizard is actually on -- it keeps its state between
    // openings, so assuming step 1 would mislabel a reopened dialog.
    doc?.getElementById?.('wizardPersonaName')?.focus?.();
  }

  /**
   * Third entry point, SAME shell, same wizard path, different starting step.
   *
   * New Persona lands on Goal & role because there is nothing to review yet;
   * Edit lands on Review & save because there is. That is the only difference
   * between them -- one dialog, one document, one save.
   *
   * The dialog is opened BEFORE the persona loads and closed again if the load
   * declines. Opening first means the user sees the shell respond to their
   * click immediately rather than after a round trip; closing on failure means
   * an unknown persona never leaves an empty dialog sitting open. Returns
   * whether it stayed open.
   */
  async function openWizardForEdit(name) {
    active = 'wizard';
    setFooter('wizard');
    showRoot();
    wizardFlow.open();

    let loaded = false;
    try {
      loaded = Boolean(await openPersonaForEdit?.(name));
    } catch (_error) {
      // A failed load must not strand an open dialog claiming to be editing.
      loaded = false;
    }
    if (!loaded) {
      close();
      return false;
    }
    // No goTo() here: personas.js's showStep(4) fires the wizard-step observer
    // registered below, which is what moves the shell. Calling goTo as well
    // would give the dialog two authorities on which step it is showing.
    return true;
  }

  function openFoundry() {
    active = 'foundry';
    setFooter('foundry');
    showRoot();
    foundryFlow.open();
    // personas.js owns starting the interview; clicking its own trigger is how
    // that happens without duplicating startFoundryInterview() here.
    (foundryTrigger || doc?.getElementById?.('openFoundryButton'))?.click?.();
  }

  // Closes both flows rather than the active one: they share a root, so
  // leaving the other's Escape handler bound would keep a dialog's keyboard
  // behaviour alive after the dialog is gone. Closing an unopened flow is a
  // no-op.
  function close() {
    wizardFlow.close();
    foundryFlow.close();
    hideRoot();
    active = null;
  }

  observeWizardStep((stepNum) => {
    if (active !== 'wizard') return;
    const id = wizardStepIdFor(stepNum);
    if (id) wizardFlow.goTo(id);
  });

  observeFoundryScreen((screen) => {
    // Checked before the path guard on purpose. personas.js binds the dialog's
    // × to foundryClose(), so this is how the close button reaches the chrome
    // on EITHER path -- and foundrySave() closes on success, where the chrome
    // must not outlive the thing it was wrapping.
    if (screen === 'closed') {
      close();
      return;
    }
    if (active !== 'foundry') return;
    const id = foundryStepIdFor(screen);
    if (id) foundryFlow.goTo(id);
  });

  return {
    openWizard,
    openWizardForEdit,
    openFoundry,
    close,
    getActivePath: () => active,
    wizardFlow,
    foundryFlow,
  };
}
