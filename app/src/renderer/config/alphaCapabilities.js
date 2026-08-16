// Single source of truth for the alpha's user-visible capability surface.
// Backend support may remain installed for migration/privacy cleanup, but an
// off capability is hidden and made inert before feature modules bind.

export const ALPHA_CAPABILITIES = Object.freeze({
  voiceCloning: false,
  teachFromEdits: false,
  deprecatedVoiceDeliveryCards: false,
  wakeWordSettings: false,
  workflowSettings: false,
  personaStressTest: false,
  deprecatedPersonaActions: false,
  structuredPersonaEditor: true,
  customVoiceWorkflow: true,
  scribeLongInputBatching: true,
});

export const ALPHA_CAPABILITY_SELECTORS = Object.freeze({
  voiceCloning: ['#voiceCloneGroup', '#sdUtilVoiceCloningPanel'],
  teachFromEdits: ['#sdTalkTeachPanel', '#sdTeachSection'],
  deprecatedVoiceDeliveryCards: ['#sdDeprecatedVoiceDelivery'],
  wakeWordSettings: ['#sdUtilWakeBackboneGroup', '#sdUtilWakeSettingsGroup'],
  workflowSettings: ['#sdUtilWorkflowGroup'],
  personaStressTest: ['#sdStressTestButton', '#sdStressTestResults'],
  deprecatedPersonaActions: ['#sdDeprecatedPersonaActions'],
});

export function applyAlphaCapabilities(root, capabilities = ALPHA_CAPABILITIES) {
  if (!root || typeof root.querySelectorAll !== 'function') return [];
  const changed = [];
  for (const [capability, selectors] of Object.entries(ALPHA_CAPABILITY_SELECTORS)) {
    if (capabilities[capability] !== false) continue;
    for (const selector of selectors) {
      for (const element of root.querySelectorAll(selector)) {
        element.hidden = true;
        element.setAttribute?.('aria-hidden', 'true');
        element.setAttribute?.('inert', '');
        element.dataset.alphaCapability = capability;
        changed.push(element);
      }
    }
  }
  return changed;
}

export function isAlphaCapabilityEnabled(name, capabilities = ALPHA_CAPABILITIES) {
  return capabilities[name] === true;
}
