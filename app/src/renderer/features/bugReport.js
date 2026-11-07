export const BUG_REPORT_ELEMENT_IDS = Object.freeze({
  open: 'sdBugReportOpen',
  dialog: 'sdBugReportDialog',
  title: 'sdBugReportTitle',
  close: 'sdBugReportClose',
  summary: 'sdBugReportSummary',
  steps: 'sdBugReportSteps',
  expected: 'sdBugReportExpected',
  actual: 'sdBugReportActual',
  contact: 'sdBugReportContact',
  preview: 'sdBugReportPreview',
  previewButton: 'sdBugReportPreviewButton',
  consent: 'sdBugReportConsent',
  destination: 'sdBugReportDestination',
  submit: 'sdBugReportSubmit',
  status: 'sdBugReportStatus',
});

export function collectBugReportElements(document) {
  return Object.fromEntries(
    Object.entries(BUG_REPORT_ELEMENT_IDS).map(([name, id]) => [name, document.getElementById(id)]),
  );
}

const LIMITS = Object.freeze({
  summary: 160,
  steps: 4000,
  expected: 4000,
  actual: 4000,
  contact: 254,
});
const FIELD_KEYS = Object.freeze(Object.keys(LIMITS));

function valueOf(element) {
  return String(element?.value ?? '').trim();
}

function announce(elements, hooks, message, error = false) {
  if (elements.status) {
    elements.status.textContent = message;
    elements.status.dataset.error = error ? 'true' : 'false';
  }
  hooks.onStatus?.(message, { error });
}

function destinationChoices(config = {}) {
  const choices = [];
  if (config.directDiscord === true) choices.push(['direct-discord', 'Send directly to Discord']);
  if (config.directEmail === true) choices.push(['direct-email', 'Send directly by email']);
  choices.push(['email', 'Copy report and open my email client']);
  choices.push(['discord', 'Copy report and open Discord']);
  return choices;
}

export function createBugReportFeature({ elements, bridge, hooks = {} }) {
  if (!elements || !bridge) throw new TypeError('Bug report elements and bridge are required');

  const listeners = [];
  let opener = null;
  let previewId = null;
  let busy = false;
  let destroyed = false;

  const listen = (element, eventName, handler) => {
    if (!element?.addEventListener) return;
    element.addEventListener(eventName, handler);
    listeners.push(() => element.removeEventListener?.(eventName, handler));
  };

  for (const [field, limit] of Object.entries(LIMITS)) {
    if (elements[field]) elements[field].maxLength = limit;
  }
  if (elements.dialog) {
    elements.dialog.hidden = true;
    elements.dialog.setAttribute('aria-modal', 'true');
    elements.dialog.setAttribute('aria-hidden', 'true');
    if (elements.title?.id) elements.dialog.setAttribute('aria-labelledby', elements.title.id);
  }
  if (elements.preview) elements.preview.hidden = true;

  const setBusy = (nextBusy) => {
    busy = Boolean(nextBusy);
    for (const key of ['close', 'previewButton', 'summary', 'steps', 'expected', 'actual', 'contact', 'consent', 'destination']) {
      if (elements[key]) elements[key].disabled = busy;
    }
    updateSubmit();
  };

  const updateSubmit = () => {
    if (elements.submit) {
      elements.submit.disabled = busy || !previewId || !elements.consent?.checked;
    }
  };

  const renderPreview = (value) => {
    if (!elements.preview) return;
    elements.preview.textContent = String(value || '');
    elements.preview.hidden = !value;
  };

  const invalidate = () => {
    const hadPreview = Boolean(previewId);
    previewId = null;
    renderPreview('');
    if (elements.consent) elements.consent.checked = false;
    updateSubmit();
    return hadPreview;
  };

  const form = () => ({
    summary: valueOf(elements.summary),
    steps: valueOf(elements.steps),
    expected: valueOf(elements.expected),
    actual: valueOf(elements.actual),
    contact: valueOf(elements.contact),
  });

  const validate = () => {
    const data = form();
    let valid = true;
    for (const [field, limit] of Object.entries(LIMITS)) {
      const required = field === 'summary' || field === 'actual';
      const invalid = data[field].length > limit || (required && !data[field]);
      elements[field]?.setAttribute('aria-invalid', invalid ? 'true' : 'false');
      if (invalid) valid = false;
    }
    return valid;
  };

  const populateDestinations = (config) => {
    const select = elements.destination;
    if (!select) return;
    select.textContent = '';
    const document = select.ownerDocument || elements.dialog?.ownerDocument;
    for (const [value, label] of destinationChoices(config)) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    }
  };

  const open = async (event) => {
    if (destroyed || busy) return;
    opener = event?.currentTarget || elements.open;
    invalidate();
    if (elements.dialog) {
      elements.dialog.hidden = false;
      elements.dialog.setAttribute('aria-hidden', 'false');
    }
    announce(elements, hooks, 'Loading report destinations…');
    setBusy(true);
    try {
      const config = await bridge.getBugReportConfig();
      populateDestinations(config);
      announce(elements, hooks, 'Describe the bug, then prepare and review the exact report.');
    } catch (error) {
      populateDestinations({});
      announce(elements, hooks, error?.message || 'Could not load automatic destinations. Manual handoff remains available.', true);
    } finally {
      setBusy(false);
      (elements.summary || elements.close)?.focus?.();
    }
  };

  const close = () => {
    if (destroyed || busy) return;
    if (elements.dialog) {
      elements.dialog.hidden = true;
      elements.dialog.setAttribute('aria-hidden', 'true');
    }
    opener?.focus?.();
    hooks.onClose?.();
  };

  const prepare = async () => {
    if (destroyed || busy) return;
    if (!validate()) {
      announce(elements, hooks, 'Summary and actual behavior are required. Check the field limits.', true);
      return;
    }
    if (typeof bridge.prepareBugReport !== 'function') {
      announce(elements, hooks, 'Bug-report preparation is unavailable.', true);
      return;
    }
    setBusy(true);
    announce(elements, hooks, 'Collecting coarse diagnostics and building the preview…');
    try {
      const result = await bridge.prepareBugReport(form());
      const nextPreviewId = typeof result?.previewId === 'string' ? result.previewId : '';
      const previewText = String(result?.previewText ?? '');
      if (!nextPreviewId || !previewText) throw new Error('The report preview was not created. Retry.');
      previewId = nextPreviewId;
      renderPreview(previewText);
      if (elements.consent) elements.consent.checked = false;
      announce(elements, hooks, 'Review every line, choose a destination, then check the consent box.');
    } catch (error) {
      previewId = null;
      renderPreview('');
      announce(elements, hooks, error?.message || 'Could not prepare the report. Retry.', true);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (destroyed || busy || !previewId || !elements.consent?.checked) return;
    if (typeof bridge.submitBugReport !== 'function') {
      announce(elements, hooks, 'Bug-report delivery is unavailable.', true);
      return;
    }
    const submittedPreviewId = previewId;
    const destination = elements.destination?.value || 'email';
    setBusy(true);
    announce(elements, hooks, 'Waiting for the system confirmation…');
    try {
      const result = await bridge.submitBugReport({ previewId: submittedPreviewId, destination });
      const status = result?.status;
      if (result?.delivered === true && status === 'delivered') {
        previewId = null;
        const requestId = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(String(result?.requestId ?? ''))
          ? String(result.requestId)
          : '';
        announce(
          elements,
          hooks,
          `Report sent successfully to BetterFingers support.${requestId ? ` Reference: ${requestId}.` : ''}`,
        );
        hooks.showToast?.('Bug report sent.', 'success');
      } else if (status === 'copied_opened_email') {
        announce(elements, hooks, 'The report was copied and your email client was opened. It has not been submitted automatically.');
        hooks.showToast?.('Report copied; finish sending it in your email client.', 'info');
      } else if (status === 'copied_opened_discord') {
        announce(elements, hooks, 'The report was copied and Discord was opened. It has not been submitted automatically.');
        hooks.showToast?.('Report copied; paste it into Discord to finish.', 'info');
      } else if (status === 'cancelled') {
        announce(elements, hooks, 'Cancelled. Nothing was sent, copied, or opened.');
      } else if (status === 'rate_limited') {
        announce(elements, hooks, 'Automatic delivery is rate-limited. Wait a minute or choose a manual handoff.', true);
      } else if (status === 'delivery_timeout') {
        announce(elements, hooks, 'Automatic delivery timed out. Nothing was confirmed sent; retry or choose a manual handoff.', true);
      } else if (status === 'delivery_failed') {
        announce(elements, hooks, 'Automatic delivery failed. Nothing was confirmed sent; retry or choose a manual handoff.', true);
      } else if (status === 'copied_open_failed') {
        announce(elements, hooks, 'The report was copied, but the destination could not be opened. Paste it manually.', true);
      } else if (status === 'in_progress') {
        announce(elements, hooks, 'This report is already being handled. Wait for the current attempt.', true);
      } else {
        announce(elements, hooks, 'No delivery was confirmed. The report remains ready to retry.', true);
      }
      if (elements.consent) elements.consent.checked = false;
    } catch (error) {
      announce(elements, hooks, error?.message || 'The report could not be handed off. Review it and retry.', true);
      if (elements.consent) elements.consent.checked = false;
    } finally {
      setBusy(false);
    }
  };

  const invalidateAfterEdit = () => {
    if (invalidate()) announce(elements, hooks, 'The report changed. Prepare a new preview before submitting.');
  };

  const handleDialogKeydown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== 'Tab' || !elements.dialog?.querySelectorAll) return;
    const focusable = Array.from(elements.dialog.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => !element.hidden);
    if (!focusable.length) return;
    const active = elements.dialog.ownerDocument?.activeElement;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus?.();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus?.();
    }
  };

  listen(elements.open, 'click', open);
  listen(elements.close, 'click', close);
  listen(elements.previewButton, 'click', prepare);
  listen(elements.submit, 'click', submit);
  for (const key of FIELD_KEYS) listen(elements[key], 'input', invalidateAfterEdit);
  listen(elements.destination, 'change', invalidateAfterEdit);
  listen(elements.consent, 'change', updateSubmit);
  listen(elements.dialog, 'keydown', handleDialogKeydown);
  updateSubmit();

  return {
    open,
    close,
    prepare,
    submit,
    invalidate,
    validate,
    destroy() {
      destroyed = true;
      while (listeners.length) listeners.pop()();
      previewId = null;
      busy = false;
      if (elements.dialog) {
        elements.dialog.hidden = true;
        elements.dialog.setAttribute('aria-hidden', 'true');
      }
    },
  };
}
