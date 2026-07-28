# Wave 5 — integration diffs outside sup-studio's lane

Author: `sup-studio`. Status: **not applied**. Every change below is in a file
this supervisor was not granted, and none of it has been written to the repo.

Two categories:

1. **Lane-blocked (sup-library-ui).** `signal-desk.html`, `signalDeskApp.js`,
   `styles/signal-desk.css` and `tests/qa/scenarios/index.mjs` are claimed by
   `sup-library-ui` under a director grant for Library sections. A coordination
   request was posted to the parent room at the start of the wave; no reply had
   arrived by handoff, so nothing was taken.
2. **Integration-owned.** `server.py` and `api/backend.js` are read-only for
   this lane by directive.

The feature modules and unit tests these diffs activate ARE applied and green.
Until the diffs land, the affected surfaces have no markup, so the Wave 5 QA
scenarios cannot execute — see §6.

---

## 1. `app/src/renderer/signal-desk.html` (sup-library-ui)

Line numbers are against `23c2181`. None of these touch a Library section.

### 1a. DELETE the Last Updated and Tags panels (lines 2895–2905)

```html
        <div class="sd-context__section">
          <span class="sd-context__section-label">Last Updated</span>
          <span class="sd-context__description" id="sdCtxLastUpdated">&mdash;</span>
        </div>

        <div class="sd-context__section">
          <span class="sd-context__section-label">Tags</span>
          <div class="sd-tags-row" id="sdCtxTags">
          </div>
          <button type="button" class="sd-tags-row__add-btn" id="sdCtxAddTagButton" aria-label="Add tag">&#65291;</button>
        </div>
```

Delete both blocks entirely. Personas carry no `updated_at`, no author and no
`tags`, so both could only ever render an em dash or an empty row. A field that
is permanently blank still tells the user a value is coming. `studioWorkspace.js`
no longer looks up any of those three ids, and
`app/tests/studioWorkspace.test.mjs` asserts their absence from the element map.

### 1b. ADD the traits disclosure (D-0006), after line 406 (`wizardTraitConfidenceBand`), inside the traits fieldset

```html
              <!--
                D-0006. The sliders above are real and are saved with the
                persona, but `use_persona_traits` is false and no control here
                may set it true, so saved values do not reach the cleanup
                prompt. A slider that silently does nothing teaches the user
                their input is being honoured; hiding the sliders would delete
                persona data they may already have authored. So the values stay
                editable and this says plainly that they are not in effect.

                There is deliberately NO checkbox, switch or "try it anyway"
                in this block. Adding one contradicts D-0006.
              -->
              <div class="sd-traits-status" id="sdStudioTraitsStatus" role="note">
                <span class="sd-traits-status__label" id="sdStudioTraitsStatusLabel"></span>
                <span class="sd-traits-status__reason" id="sdStudioTraitsStatusReason"></span>
                <span class="sd-traits-status__detail" id="sdStudioTraitsStatusDetail"></span>
              </div>
```

Text content is written by `studioWorkspace.js`'s `renderTraitsStatus()` from the
frozen `PERSONA_TRAITS_STATUS`, never from markup, so the wording cannot drift
from the decision. Leave the elements empty here.

### 1c. ADD the two disclosed toggles (D-0005), before line 2415 (`</section>` closing `sdSetSectionAiCleanup`)

```html
              <!--
                D-0005 disclosed toggles. Six required disclosures each: data
                used, what it may change, what it must preserve, default,
                inspect path, gate status. All six spans are filled by
                settingsWorkspace.js's renderDisclosedToggles() from
                DISCLOSED_TOGGLES -- do not hard-code the text here, or the
                disclosure and the behaviour can drift apart.
              -->
              <div class="sd-set-row sd-set-row--disclosed" data-search-row data-search-label="speech delivery signals">
                <div class="sd-set-row__label">
                  <span class="sd-set-row__label-text">Use speech delivery signals</span>
                  <dl class="sd-disclosure">
                    <dt>Data it uses</dt><dd id="sdSetDeliverySignalsDataUsed"></dd>
                    <dt>What it may change</dt><dd id="sdSetDeliverySignalsMayChange"></dd>
                    <dt>What it must preserve</dt><dd id="sdSetDeliverySignalsMustPreserve"></dd>
                    <dt>Default</dt><dd id="sdSetDeliverySignalsDefault"></dd>
                    <dt>Preservation gate</dt><dd id="sdSetDeliverySignalsGate"></dd>
                  </dl>
                  <button type="button" class="sd-link-btn" id="sdSetDeliverySignalsInspect"></button>
                </div>
                <div class="sd-set-row__control">
                  <input type="checkbox" class="sd-set-checkbox" id="sdSetUseDeliverySignals" />
                </div>
              </div>

              <!--
                The audience control ships DISABLED. Enabling it is a release
                gate decision that has not been made (D-0005). Note also that
                `use_audience_context` is absent from SETTINGS_FIELD_KEYS, so
                no save path can carry it even if this attribute is removed.
              -->
              <div class="sd-set-row sd-set-row--disclosed" data-search-row data-search-label="audience context contact">
                <div class="sd-set-row__label">
                  <span class="sd-set-row__label-text">Use selected contact/audience context</span>
                  <dl class="sd-disclosure">
                    <dt>Data it uses</dt><dd id="sdSetAudienceContextDataUsed"></dd>
                    <dt>What it may change</dt><dd id="sdSetAudienceContextMayChange"></dd>
                    <dt>What it must preserve</dt><dd id="sdSetAudienceContextMustPreserve"></dd>
                    <dt>Default</dt><dd id="sdSetAudienceContextDefault"></dd>
                    <dt>Preservation gate</dt><dd id="sdSetAudienceContextGate"></dd>
                  </dl>
                  <button type="button" class="sd-link-btn" id="sdSetAudienceContextInspect"></button>
                </div>
                <div class="sd-set-row__control">
                  <input type="checkbox" class="sd-set-checkbox" id="sdSetUseAudienceContext" disabled />
                </div>
              </div>
```

### 1d. ADD contacts manage + clear, after line 2713 (`sdContactNewButton`)

```html
        <button type="button" class="sd-link-btn" id="sdContactManageButton">Manage contacts</button>
        <!--
          Clearing is a separate action from picking "No one in particular"
          only in how it is reached; both end in the same state and both
          persist. A sticky selection that un-sticks only in the UI would come
          back on the next launch.
        -->
        <button type="button" class="sd-link-btn" id="sdContactClearButton">Clear applied contact</button>

        <!--
          The manage list. "Manage" used to open the CREATE wizard, which is
          how contacts ended up create-only (D-0004): there was no path to an
          existing contact at all. Rows are built by contacts.js and carry the
          contact id in a dataset entry.
        -->
        <ul class="sd-contact-manage" id="sdContactManageList"></ul>
        <p class="sd-context__empty-text" id="sdContactManageEmpty" hidden>No contacts yet.</p>
```

### 1e. ADD the status-bar contact cell, after line 3091 (the Persona cell's closing `</div>`)

```html
    <!--
      Hidden until a contact is applied, unlike every other cell. "No one in
      particular" is the default and a real choice, not an unknown, so a
      permanent cell reading "—" beside it would turn the default into a gap
      the user feels invited to fill. statusBar.js toggles [hidden].
    -->
    <div class="sd-statusbar__cell" id="sdStatusContactCell" hidden>
      <span class="sd-statusbar__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.5"></circle><path d="M5 20a7 7 0 0 1 14 0"></path></svg>
      </span>
      <span class="sd-statusbar__text">
        <span class="sd-statusbar__label">Writing to</span>
        <span class="sd-statusbar__value" id="sdStatusContactValue"></span>
      </span>
    </div>
```

---

## 2. `app/src/renderer/bootstrap/signalDeskApp.js` (sup-library-ui)

### 2a. Pass the document to `createPersonasFeature` and capture its edit entry (~line 562)

```js
  const personas = createPersonasFeature({
    elements: { ...collectPersonaWizardElements(doc), currentPresetSelect: settingsElements.fields?.current_preset },
    ui: { setMessage, showToast },
    doc,                       // <-- ADD: stops personas.js's Foundry/step
                               //     lookups falling back to the ambient
                               //     document (there is now one document of
                               //     record, not whichever page is loaded)
    hooks: { /* unchanged */ },
  });
```

### 2b. Give the flow the loader, and Studio the Edit hook

```js
  personaFlow = createPersonaFlow({
    root: doc.getElementById('foundryOverlay'),
    footer: doc.getElementById('sdPersonaFlowFooter'),
    foundryTrigger: doc.getElementById('openFoundryButton'),
    doc,
    openPersonaForEdit: personas.openPersonaForEdit,   // <-- ADD
  });
```

and in the Studio hooks (~line 527, beside `onNewPersonaRequested`):

```js
      onEditPersonaRequested: (name) => personaFlow?.openWizardForEdit(name),   // <-- ADD
      getActivePersonaName: () => String(profileSettings?.current_preset ?? '').trim(),  // already present
```

Without 2b, Studio's Edit toasts "Persona wizard isn't wired into this page yet"
— which is correct behaviour, just not the finished feature. The old
cross-document fallback is deleted either way.

### 2c. Contacts: manage, edit, delete, clear, and the status-bar cell (~line 601)

```js
  const contacts = createContactsFeature({
    elements: collectContactElements(doc),
    hooks: {
      onCreateRequested: () => contactWizard.open(),
      onEditRequested: (contact) => contactWizard.openForEdit(contact),   // <-- ADD
      onManageRequested: () => {},                                       // <-- ADD (list renders itself)
      onApplied: (contact) => statusBar.setContact(contact),             // <-- ADD
      showToast,                                                          // <-- ADD
      onSelect: async (contactId) => { /* unchanged */ },
    },
  });
```

`confirmFn` is intentionally left unset: it defaults to `window.confirm`, which
is what the persona delete path already uses.

The wizard's `onSaved` should refresh but still not auto-apply:

```js
      onSaved: (contact, meta) => {
        showToast(`${meta?.edited ? 'Updated' : 'Saved'} contact "${contact?.name || ''}".`, 'success');
        refreshContactsAndShare().catch(() => {});
      },
```

Also restore the applied contact into the rail on boot (~line 728):

```js
    .then((active) => {
      contacts.setSelected(active?.contact_id || '');
      statusBar.setContact(contacts.getSelected());   // <-- ADD
    })
```

### 2d. Settings inspect hook (optional)

```js
      onInspectToggleData: (key, target) => { /* route to Privacy or Library */ },
```

Omit it and the link falls back to `goToSection('privacy')`, which is a real
destination — the tests cover both paths.

---

## 3. `app/src/renderer/styles/signal-desk.css` (sup-library-ui)

New classes needing styling, all additive:
`.sd-traits-status`, `.sd-traits-status__label`, `.sd-traits-status__reason`,
`.sd-traits-status__detail`, `.sd-set-row--disclosed`, `.sd-disclosure`,
`.sd-contact-manage`, `.sd-contact-row`, `.sd-contact-row__name`,
`.sd-contact-row__detail`, `.sd-contact-row__edit`, `.sd-contact-row__delete`.

Nothing breaks without these — the markup degrades to unstyled but readable and
every assertion in the QA scenarios still holds.

---

## 4. `app/tests/qa/scenarios/index.mjs` (sup-library-ui)

```js
import { wave5StudioScenarios } from './wave5-studio.mjs';
// ... and add `...wave5StudioScenarios` to the exported array, alongside the
// other `ui: 'signal-desk-prod'` entries.
```

The scenario file itself is applied at
`app/tests/qa/scenarios/wave5-studio.mjs` (13 scenarios) and claimed by
sup-studio. It is a new file and overlaps nothing of sup-library-ui's.

---

## 5. Retroactive contact application (integration-owned)

**This is the one part of the D-0004 contract that cannot be completed in this
lane.** `contact_id` is write-once at draft creation: `create_draft()` accepts it
(`server.py:936`, `backend/stores/drafts.py:223`) and the dictation path passes
the profile's `active_contact_id` (`server.py:1933`), but no route changes it on
an existing draft. `/drafts/{id}/edit` only touches `final_text`.

No renderer control for this shipped. A button that 404s is worse than an
absent one, so the UI affordance is withheld until the route exists.

### 5a. `server.py` — new route (suggested, beside `/drafts/{draft_id}/edit`, ~line 4238)

```python
class DraftContactRequest(BaseModel):
    contact_id: str = ""


@app.post("/drafts/{draft_id}/contact")
async def set_draft_contact(draft_id: int, request: DraftContactRequest):
    """Apply (or clear) a contact on an existing draft.

    Recording the audience after the fact is the same act as recording it at
    dictation time -- it is metadata about who the message is for, and it is
    what lets Library filter by contact. It does NOT re-run cleanup: the draft
    text was produced without that context and rewriting it here would change
    the user's words behind their back.

    An empty contact_id clears the field. A non-empty one must name a contact
    that exists, so a deleted contact cannot be re-attached by id.
    """
    contact_id = (request.contact_id or "").strip()
    if contact_id:
        from backend.services.contacts import ContactStore
        if ContactStore().get(contact_id) is None:
            raise HTTPException(status_code=404, detail=f"Contact '{contact_id}' not found.")

    with draft_lock:
        draft = get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        draft["contact_id"] = contact_id or None
        draft["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = dict(draft)

    save_draft_history(changed_draft_id=draft_id)
    return response
```

### 5b. `app/src/renderer/api/backend.js` — matching call

```js
async function setDraftContact(draftId, contactId, timeoutMs = 10000) {
  return postJson(`${BACKEND_ORIGIN}/drafts/${encodeURIComponent(draftId)}/contact`,
    { contact_id: contactId || '' }, timeoutMs);
}
// ...and add `setDraftContact` to the exports.
```

### 5c. Electron proxy allowlist

`POST /drafts/:id/contact` must be added wherever `POST /drafts/:id/edit` is
already allowlisted, or the renderer cannot reach it.

### 5d. No `data_categories.py` change needed

Checked and none required. `contacts` is already registered as a `personal`,
`in_export=True`, `user_text=True` category (`data_categories.py:114`), the
privacy report lists the contacts file (`server.py:3289`), and the wipe clears
the store and reports `contacts_cleared` (`server.py:3612–3653`). A draft's
`contact_id` lives inside the drafts category, which is already covered. So the
privacy contract needs no widening for Wave 5 — this was verified, not assumed.

---

## 6. What this blocks

Until §1, §2 and §4 land, `app/tests/qa/scenarios/wave5-studio.mjs` **cannot
run**: the ids it asserts on do not exist in the page and it is not registered.
The 13 scenarios are written and shape-validated but **unexecuted**, and this
should be read as "QA authored", not "QA passed".

The renderer unit tests are unaffected and green (1105/1105), because they
exercise the feature modules directly rather than through the page.
