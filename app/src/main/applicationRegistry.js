// Confirmed application registry (Wave 9, D-0011) — main process.
//
// A workflow may only name an application that is IN this registry, and an
// entry only gets in here because the user confirmed it. That is the whole
// security story of the launch half of Wave 9: `backend/services/action_validator.py`
// resolves every `launch_app` / `focus_app` / `wait_for_process` step against
// the confirmed set, and there is no other way for a workflow to express "this
// app", so a workflow cannot escape the registry.
//
// DISCOVERY SHOWS, IT DOES NOT TRUST. `discover()` scans `.desktop` files and
// asks flatpak what is installed, and everything it returns carries
// `confirmed: false`. A `.desktop` file is a text file any package (or any
// download) can drop into `~/.local/share/applications`, with a `Name` it chose
// and an `Exec` line it wrote. Treating that as an approved launch target would
// mean the answer to "what may a voice phrase start?" is decided by whatever is
// on disk. So discovery populates a picker, and `confirm()` — display name,
// launch method, executable or app id, optional URI, associated application
// profile — is what actually creates a registry entry.
//
// EXEC LINES ARE NOT COMMANDS HERE. A `.desktop` Exec line is parsed only far
// enough to suggest an executable path to the user in the confirm form. It is
// never assembled into a string that gets run: `applicationLauncher.js` builds
// an argv array from the CONFIRMED fields, and the field codes (%f, %U, …)
// are dropped rather than expanded.
//
// STORAGE. One versioned JSON file under the unified data root
// (`userDataRoot.js`, the Node mirror of `app_paths.resolve_base()`, so
// BETTERFINGERS_DATA_DIR is honoured), written atomically via a temp file and a
// rename. Same shape and the same failure behaviour as the Python stores: a
// corrupt file degrades to an empty registry rather than taking the feature
// down, and a failed write leaves the previous file intact.
//
// Every dependency is injectable (`fs`, `execFile`, `env`, `homedir`) so the
// whole module is unit-testable with no filesystem and no desktop session.

const nodePath = require('node:path');
const nodeFs = require('node:fs');
const nodeOs = require('node:os');
const { resolveUserDataRoot } = require('./userDataRoot');

const SCHEMA_VERSION = 1;
const REGISTRY_FILENAME = 'application_registry.json';

// Mirrors backend/services/action_validator.py LAUNCH_METHODS, in the same
// Linux priority order. Both sides are asserted against this list.
const LAUNCH_METHODS = ['desktop_entry', 'flatpak', 'uri', 'executable', 'steam'];

// Which confirmed field each method needs. Mirrors LAUNCH_METHOD_FIELD.
const LAUNCH_METHOD_FIELD = {
  desktop_entry: 'desktop_entry',
  flatpak: 'flatpak_id',
  uri: 'uri',
  executable: 'executable',
  steam: 'steam_uri',
};

const MAX_ENTRIES = 200;
const MAX_CANDIDATES = 500;
const MAX_TEXT = 120;
const MAX_URI = 2048;
const MAX_PATH = 4096;
// A .desktop file is small; anything larger is not one, and reading it whole
// into memory to find that out is the avoidable part.
const MAX_DESKTOP_FILE_BYTES = 64 * 1024;

const ID_RE = /^[a-z0-9][a-z0-9_]{0,63}$/;

function normalizeId(value) {
  const token = String(value == null ? '' : value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
  return ID_RE.test(token) ? token : '';
}

/**
 * Bounded, control-character-free text.
 *
 * Written as an explicit code-point filter rather than a regex literal, because
 * a regex over the C0 range is exactly the kind of source line that gets
 * corrupted by a copy-paste and then silently matches nothing. Control
 * characters matter here: a display name or a path carrying a newline is how
 * one value becomes two the moment something downstream splits on it.
 */
function cleanText(value, limit = MAX_TEXT) {
  const text = String(value == null ? '' : value);
  let out = '';
  for (const ch of text) {
    const code = ch.codePointAt(0);
    if (code < 0x20 || (code >= 0x7f && code <= 0x9f)) continue;
    out += ch;
  }
  return out.trim().slice(0, limit);
}

/**
 * A URI a registry entry may carry, or ''.
 *
 * Same rule as the Python side (`backend/domain/actions.normalize_uri`): a
 * scheme is required, spaces are refused rather than percent-encoded, and the
 * code-bearing schemes are refused by name so the reason can say so.
 */
function normalizeUri(value) {
  const text = cleanText(value, MAX_URI + 1);
  if (!text || text.length > MAX_URI) return '';
  if (/\s/.test(text)) return '';
  const match = /^([a-z][a-z0-9+.-]*):/i.exec(text);
  if (!match) return '';
  const scheme = match[1].toLowerCase();
  if (scheme === 'javascript' || scheme === 'data' || scheme === 'vbscript' || scheme === 'file') return '';
  return text;
}

function uriScheme(uri) {
  const match = /^([a-z][a-z0-9+.-]*):/i.exec(String(uri || ''));
  return match ? match[1].toLowerCase() : '';
}

// --- .desktop parsing --------------------------------------------------------

/**
 * The `[Desktop Entry]` group's keys. Later groups (`[Desktop Action …]`) are
 * ignored on purpose: an action group's Exec is a different command wearing the
 * same file's name, and picking one up here would suggest an executable the
 * entry's own Name does not describe.
 */
function parseDesktopEntry(text) {
  const out = {};
  let inEntry = false;
  for (const rawLine of String(text || '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    if (line.startsWith('[')) {
      inEntry = line === '[Desktop Entry]';
      continue;
    }
    if (!inEntry) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    // Localised keys (Name[de]) are skipped: the picker shows one language and
    // the unlocalised value is the one every other tool reports.
    if (key.includes('[')) continue;
    if (!(key in out)) out[key] = line.slice(eq + 1).trim();
  }
  return out;
}

/**
 * The executable an Exec line names, with field codes dropped.
 *
 * Returns the program token only. Arguments in the Exec line are deliberately
 * dropped rather than carried: they are the vendor's defaults for a
 * double-click, they routinely contain %U/%f placeholders the desktop
 * environment fills in, and inventing values for those is exactly the kind of
 * guess this feature refuses to make. A user who needs arguments confirms them.
 */
function execProgram(execLine) {
  const text = String(execLine || '').trim();
  if (!text) return '';
  // Quoted first token wins; otherwise the first whitespace-delimited token.
  const quoted = /^"([^"]+)"/.exec(text);
  const token = quoted ? quoted[1] : text.split(/\s+/)[0];
  if (!token || token.startsWith('%')) return '';
  return cleanText(token, MAX_PATH);
}

function desktopDirs({ env, homedir }) {
  const dirs = [];
  const dataHome = env.XDG_DATA_HOME || nodePath.join(homedir(), '.local', 'share');
  dirs.push(nodePath.join(dataHome, 'applications'));
  const dataDirs = env.XDG_DATA_DIRS || '/usr/local/share:/usr/share';
  for (const dir of String(dataDirs).split(':')) {
    if (dir) dirs.push(nodePath.join(dir, 'applications'));
  }
  // De-duplicated, order preserved: the user's own directory shadows the
  // system ones, which is the same precedence the desktop itself applies.
  return dirs.filter((dir, index) => dirs.indexOf(dir) === index);
}

// --- the module ---------------------------------------------------------------

/**
 * @param {object} deps
 * @param {object} [deps.fs]         node:fs-shaped { readFileSync, writeFileSync, readdirSync, renameSync, mkdirSync, statSync }
 * @param {function} [deps.execFile] node:child_process execFile (callback style) — flatpak discovery only
 * @param {object} [deps.env]
 * @param {function} [deps.homedir]
 * @param {string} [deps.rootDir]    overrides the resolved data root (tests)
 */
function createApplicationRegistry({
  fs = nodeFs,
  execFile = null,
  env = process.env,
  homedir = nodeOs.homedir,
  rootDir = null,
} = {}) {
  const root = rootDir || resolveUserDataRoot({ env, homedir });
  const filePath = nodePath.join(root, REGISTRY_FILENAME);

  function emptyStore() {
    return { schema_version: SCHEMA_VERSION, entries: {} };
  }

  function coerceEntry(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const id = normalizeId(raw.id);
    if (!id) return null;
    const method = LAUNCH_METHODS.includes(raw.launch_method) ? raw.launch_method : '';
    const entry = {
      schema_version: SCHEMA_VERSION,
      id,
      display_name: cleanText(raw.display_name) || id,
      launch_method: method,
      desktop_entry: cleanText(raw.desktop_entry, MAX_PATH),
      flatpak_id: cleanText(raw.flatpak_id),
      executable: cleanText(raw.executable, MAX_PATH),
      uri: normalizeUri(raw.uri),
      steam_uri: normalizeUri(raw.steam_uri),
      profile_id: normalizeId(raw.profile_id),
      // A stored entry is confirmed by definition — the store is only ever
      // written by confirm(). Read back defensively anyway: a hand-edited file
      // that flipped this to true for an entry with no launch method still has
      // to fail the launcher's own check, which it does.
      confirmed: true,
    };
    entry.uri_scheme = uriScheme(entry.uri);
    return entry;
  }

  function load() {
    let text = '';
    try {
      text = fs.readFileSync(filePath, 'utf8');
    } catch {
      return emptyStore();
    }
    let data = null;
    try {
      data = JSON.parse(text);
    } catch {
      // Corrupt file: degrade to empty rather than taking the feature down.
      // Nothing is deleted — the file stays for support to look at.
      return emptyStore();
    }
    const entries = {};
    const raw = data && typeof data === 'object' ? data.entries : null;
    const items = Array.isArray(raw)
      ? raw
      : (raw && typeof raw === 'object' ? Object.values(raw) : []);
    for (const item of items) {
      const entry = coerceEntry(item);
      if (entry) entries[entry.id] = entry;
    }
    return { schema_version: SCHEMA_VERSION, entries };
  }

  function save(data) {
    const text = JSON.stringify(data, null, 2);
    const tmp = `${filePath}.tmp`;
    try {
      fs.mkdirSync(root, { recursive: true });
    } catch { /* the write below reports the real problem */ }
    fs.writeFileSync(tmp, text, 'utf8');
    fs.renameSync(tmp, filePath);
  }

  // --- discovery ------------------------------------------------------------

  function discoverDesktopEntries() {
    const candidates = [];
    for (const dir of desktopDirs({ env, homedir })) {
      let names = [];
      try {
        names = fs.readdirSync(dir);
      } catch {
        continue;
      }
      for (const name of names) {
        if (!String(name).endsWith('.desktop')) continue;
        if (candidates.length >= MAX_CANDIDATES) return candidates;
        let text = '';
        try {
          const full = nodePath.join(dir, name);
          const stat = typeof fs.statSync === 'function' ? fs.statSync(full) : null;
          if (stat && stat.size > MAX_DESKTOP_FILE_BYTES) continue;
          text = fs.readFileSync(full, 'utf8');
        } catch {
          continue;
        }
        const entry = parseDesktopEntry(text);
        if (entry.Type && entry.Type !== 'Application') continue;
        if (String(entry.NoDisplay || '').toLowerCase() === 'true') continue;
        const display = cleanText(entry.Name);
        if (!display) continue;
        candidates.push({
          confirmed: false,
          source: 'desktop_entry',
          suggested_id: normalizeId(String(name).replace(/\.desktop$/, '')),
          display_name: display,
          desktop_entry: String(name),
          executable: execProgram(entry.Exec),
          flatpak_id: cleanText(entry['X-Flatpak']),
          uri: '',
        });
      }
    }
    return candidates;
  }

  function discoverFlatpaks() {
    if (typeof execFile !== 'function') return Promise.resolve([]);
    return new Promise((resolve) => {
      let settled = false;
      const done = (value) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      try {
        // Argument array, never a shell string — the same rule the launcher
        // follows, applied to the discovery call as well.
        execFile('flatpak', ['list', '--app', '--columns=application,name'],
          { timeout: 4000, maxBuffer: 1024 * 512 }, (error, stdout) => {
            if (error) return done([]);
            const out = [];
            for (const line of String(stdout || '').split(/\r?\n/)) {
              const [appId, name] = line.split('\t');
              const id = cleanText(appId);
              if (!id) continue;
              out.push({
                confirmed: false,
                source: 'flatpak',
                suggested_id: normalizeId(id.split('.').pop() || id),
                display_name: cleanText(name) || id,
                desktop_entry: '',
                executable: '',
                flatpak_id: id,
                uri: '',
              });
              if (out.length >= MAX_CANDIDATES) break;
            }
            done(out);
          });
      } catch {
        done([]);
      }
    });
  }

  /**
   * Everything this machine appears to have, all `confirmed: false`.
   *
   * De-duplicated by flatpak id then by suggested id, keeping the first
   * occurrence: a flatpak ships its own .desktop file, so the same application
   * legitimately shows up twice and a picker with two identical rows is a
   * picker the user cannot answer.
   */
  async function discover() {
    const seen = new Set();
    const out = [];
    const all = [...discoverDesktopEntries(), ...(await discoverFlatpaks())];
    for (const candidate of all) {
      const key = candidate.flatpak_id || candidate.suggested_id || candidate.display_name;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(candidate);
      if (out.length >= MAX_CANDIDATES) break;
    }
    out.sort((a, b) => a.display_name.localeCompare(b.display_name));
    return out;
  }

  // --- confirmation ---------------------------------------------------------

  /**
   * Create or replace a confirmed entry. This is the ONLY writer.
   *
   * Refuses rather than storing a half-usable entry: an entry whose declared
   * launch method has no value behind it would sit in the registry looking
   * valid and fail at the moment the user's workflow ran.
   */
  function confirm(payload) {
    const entry = coerceEntry(payload);
    if (!entry) {
      return {
        ok: false,
        error: 'invalid_id',
        message: 'Give the application an id of lowercase letters, digits and underscores.',
      };
    }
    if (!entry.launch_method) {
      return {
        ok: false,
        error: 'invalid_launch_method',
        message: `Choose how to start it: ${LAUNCH_METHODS.join(', ')}.`,
      };
    }
    const requiredField = LAUNCH_METHOD_FIELD[entry.launch_method];
    if (!entry[requiredField]) {
      return {
        ok: false,
        error: 'missing_launch_target',
        message: `"${entry.launch_method}" needs a ${requiredField}.`,
      };
    }
    const data = load();
    if (!data.entries[entry.id] && Object.keys(data.entries).length >= MAX_ENTRIES) {
      return {
        ok: false,
        error: 'cap_reached',
        message: `You already have ${MAX_ENTRIES} confirmed applications.`,
      };
    }
    data.entries[entry.id] = entry;
    try {
      save(data);
    } catch (error) {
      return { ok: false, error: 'write_failed', message: String(error && error.message) };
    }
    return { ok: true, entry };
  }

  function remove(id) {
    const key = normalizeId(id);
    if (!key) return { ok: false, error: 'invalid_id' };
    const data = load();
    if (!data.entries[key]) return { ok: true, removed: false };
    delete data.entries[key];
    try {
      save(data);
    } catch (error) {
      return { ok: false, error: 'write_failed', message: String(error && error.message) };
    }
    return { ok: true, removed: true };
  }

  function list() {
    const data = load();
    return Object.keys(data.entries).sort().map((id) => data.entries[id]);
  }

  function get(id) {
    const key = normalizeId(id);
    if (!key) return null;
    return load().entries[key] || null;
  }

  /** Privacy clear — the registry records which applications this person runs. */
  function clearAll() {
    try {
      save(emptyStore());
    } catch (error) {
      return { ok: false, error: 'write_failed', message: String(error && error.message) };
    }
    return { ok: true };
  }

  return { discover, confirm, remove, list, get, clearAll, path: filePath };
}

module.exports = {
  createApplicationRegistry,
  parseDesktopEntry,
  execProgram,
  normalizeId,
  normalizeUri,
  uriScheme,
  desktopDirs,
  cleanText,
  LAUNCH_METHODS,
  LAUNCH_METHOD_FIELD,
  SCHEMA_VERSION,
  REGISTRY_FILENAME,
  MAX_ENTRIES,
};
