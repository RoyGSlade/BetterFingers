import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  SMALLEST_SUPPORTED_TTS_MODEL,
  TTS_MODEL_COMPATIBILITY,
  assessTtsCompatibility,
} from '../src/renderer/lib/modelCompat.mjs';

const repoRoot = new URL('../../', import.meta.url);
const compatibilitySourceUrl = new URL('../src/renderer/lib/modelCompat.mjs', import.meta.url);
const citationPattern = /([A-Za-z0-9_/-]+\.py)::([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)/g;

// Mask comments and quoted text before recognizing declarations. Preserve
// whitespace/newlines so docstrings and fake declarations cannot change scope.
// This is a bounded textual resolver for explicit def/class declarations,
// not a Python interpreter or a resolver for imports/dynamic assignments.
function maskPythonTrivia(source) {
  let result = '';
  let quote = null;
  let comment = false;
  for (let i = 0; i < source.length;) {
    const char = source[i];
    if (comment) {
      result += char === '\n' || char === '\r' ? char : ' ';
      i += 1;
      if (char === '\n') comment = false;
    } else if (quote) {
      if (char === '\\') {
        result += ' ';
        i += 1;
        if (i < source.length) {
          result += source[i] === '\n' || source[i] === '\r' ? source[i] : ' ';
          i += 1;
        }
      } else if (source.startsWith(quote, i)) {
        result += ' '.repeat(quote.length);
        i += quote.length;
        quote = null;
      } else {
        result += char === '\n' || char === '\r' ? char : ' ';
        i += 1;
      }
    } else if (char === '#') {
      result += ' ';
      i += 1;
      comment = true;
    } else if (char === '"' || char === "'") {
      quote = source.startsWith(char.repeat(3), i) ? char.repeat(3) : char;
      result += ' '.repeat(quote.length);
      i += quote.length;
    } else {
      result += char;
      i += 1;
    }
  }
  return result;
}

function declaredPythonSymbols(source) {
  const symbols = new Map();
  const scopes = [];
  let bracketDepth = 0;
  let continued = false;
  for (const line of maskPythonTrivia(source).split(/\r?\n/)) {
    const statement = line.trim();
    if (!statement) continue;
    if (bracketDepth === 0 && !continued) {
      // Python expands tabs to the next multiple of eight, not a fixed width.
      let indent = 0;
      for (const char of line.match(/^[ \t]*/)[0]) {
        indent = char === '\t' ? indent + 8 - (indent % 8) : indent + 1;
      }
      while (scopes.length && indent <= scopes.at(-1).indent) scopes.pop();
      const declaration = statement.match(/^(?:async\s+)?(class|def)\s+([A-Za-z_]\w*)\b/);
      if (declaration) {
        const [, kind, name] = declaration;
        symbols.set([...scopes.map((scope) => scope.name), name].join('.'), {
          kind,
          owners: scopes.map((scope) => scope.kind),
        });
        // Only a colon outside brackets starts the suite: parameter/return
        // annotations must not make a multiline method look like an inline one.
        let headerDepth = 0;
        let inlineSuite = false;
        for (let i = 0; i < statement.length; i += 1) {
          const char = statement[i];
          if ('([{'.includes(char)) headerDepth += 1;
          if (')]}'.includes(char)) headerDepth -= 1;
          if (char === ':' && headerDepth === 0) {
            inlineSuite = Boolean(statement.slice(i + 1).trim());
            break;
          }
        }
        // A one-line suite has no following indented body to own.
        if (!inlineSuite) scopes.push({ kind, name, indent });
      }
    }
    for (const char of line) {
      if ('([{'.includes(char)) bracketDepth += 1;
      if (')]}'.includes(char)) bracketDepth -= 1;
    }
    continued = /\\\s*$/.test(line);
  }
  return symbols;
}

function assertCitationResolves(citation, readSource = (path) => readFileSync(new URL(path, repoRoot), 'utf8')) {
  const match = citation.match(/^([A-Za-z0-9_/-]+\.py)::([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)$/);
  assert.ok(match, 'Malformed Python symbol citation: ' + citation);
  const [, path, symbol] = match;
  const declaration = declaredPythonSymbols(readSource(path)).get(symbol);
  assert.ok(
    declaration && declaration.owners.every((kind) => kind === 'class'),
    'Unresolved Python symbol citation: ' + citation,
  );
}

test('all evidence fields and comments resolve against actual Python declarations', () => {
  const source = readFileSync(compatibilitySourceUrl, 'utf8');
  assert.doesNotMatch(source, /\.py:\d/, 'line-number evidence must not return');
  const citations = new Set([...source.matchAll(citationPattern)].map((match) => match[0]));
  assert.ok(citations.size > 0, 'the module must retain source evidence');
  for (const row of [...TTS_MODEL_COMPATIBILITY, SMALLEST_SUPPORTED_TTS_MODEL]) {
    for (const citation of row.evidence.split(';').map((part) => part.trim())) {
      assertCitationResolves(citation);
      assert.ok(citations.has(citation), 'each evidence field is covered by source scanning');
    }
  }
  for (const citation of citations) assertCitationResolves(citation);
});

test('renaming an actual cited method in memory makes its evidence fail', () => {
  const citation = 'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend';
  const source = readFileSync(new URL('backend/tts/tts_engine.py', repoRoot), 'utf8');
  const mutated = source.replace(/(\bdef\s+)_load_kokoro_onnx_backend\b/, '$1renamed_onnx_loader');
  assert.notEqual(mutated, source, 'the drift simulation must rename the declaration');
  assertCitationResolves(citation, () => source);
  assert.throws(() => assertCitationResolves(citation, () => mutated), /Unresolved Python symbol citation/);
});

test('a method on another class or nested in a method cannot satisfy a class citation', () => {
  const source = [
    'class ReviewTTSEngine:',
    '    def outer(self, name: str) -> str:',
    '        def _load_kokoro_onnx_backend():',
    '            pass',
    '',
    'class OtherEngine:',
    '    async def _load_kokoro_onnx_backend(self):',
    '        pass',
    '',
    'def _load_kokoro_onnx_backend():',
    '    pass',
    '# class ReviewTTSEngine: def _load_kokoro_onnx_backend(self): pass',
    'example = """',
    'class ReviewTTSEngine:',
    '    def _load_kokoro_onnx_backend(self):',
    '        pass',
    '"""',
  ].join('\n');
  assertCitationResolves('fixture.py::OtherEngine._load_kokoro_onnx_backend', () => source);
  assertCitationResolves('fixture.py::_load_kokoro_onnx_backend', () => source);
  assert.throws(
    () => assertCitationResolves('fixture.py::ReviewTTSEngine._load_kokoro_onnx_backend', () => source),
    /Unresolved Python symbol citation/,
  );
});

test('a same-named function cannot stand in for the cited owning class', () => {
  const source = [
    'def ReviewTTSEngine():',
    '    def _load_kokoro_onnx_backend():',
    '        pass',
  ].join('\n');
  assert.throws(
    () => assertCitationResolves('fixture.py::ReviewTTSEngine._load_kokoro_onnx_backend', () => source),
    /Unresolved Python symbol citation/,
  );
});

test('decorated methods and multiline headers retain their lexical owner', () => {
  const source = [
    'class Outer:',
    '    class Inner(',
    '        Base,',
    '    ):',
    '        @staticmethod',
    '        async def load(',
    '            value: str = "class Fake: def ghost(): pass",',
    '        ):',
    '            pass',
    '',
    'async def top_level(): pass',
  ].join('\n');
  assertCitationResolves('fixture.py::Outer.Inner.load', () => source);
  assertCitationResolves('fixture.py::top_level', () => source);
  assert.throws(() => assertCitationResolves('fixture.py::Outer.load', () => source), /Unresolved/);
  assert.throws(() => assertCitationResolves('fixture.py::Fake.ghost', () => source), /Unresolved/);
});

test('unknown runtime/model pairs remain offered with a caution', () => {
  const result = assessTtsCompatibility({
    runtime: 'future-runtime',
    model: 'user-installed-tts-model',
    voiceId: 'user_voice',
  });

  assert.equal(result.known, false);
  assert.equal(result.knownBad, false);
  assert.equal(result.offered, true, 'missing table rows must fail open');
  assert.match(result.caution, /may not be supported by the selected runtime/);
});

test('native runtime flags an ONNX model as a known-bad pairing', () => {
  const result = assessTtsCompatibility({
    runtime: 'native',
    model: 'kokoro-v1.0.int8.onnx',
  });

  assert.equal(result.known, true);
  assert.equal(result.knownBad, true);
  assert.equal(result.compatible, false);
  assert.equal(result.offered, false, 'an explicit incompatibility is not offered');
  assert.match(result.caution, /may not be supported by the selected runtime/);
});

test('loaded runtime voice capabilities reject voices absent from the backend truth', () => {
  const result = assessTtsCompatibility({
    runtime: 'onnx',
    model: 'kokoro-v1.0.onnx',
    voiceId: 'bm_george',
    runtimeCapabilities: {
      model_id: 'kokoro-v1.0.onnx',
      supported_voice_ids: ['af_heart', 'bf_emma'],
      blend_capable: true,
    },
  });

  assert.equal(result.knownBad, true);
  assert.equal(result.offered, false);
  assert.match(result.caution, /not present in the loaded TTS runtime/);
});

test('loaded runtime blend capability rejects blending when the backend says it is unavailable', () => {
  const result = assessTtsCompatibility({
    runtime: 'native',
    model: 'kokoro-v1.0.onnx',
    capability: 'blend',
    runtimeCapabilities: { blend_capable: false },
  });

  assert.equal(result.knownBad, true);
  assert.equal(result.offered, false);
  assert.match(result.caution, /blending is not supported/);
});

test('the smallest supported TTS variant is the declared int8 Kokoro artifact', () => {
  assert.equal(SMALLEST_SUPPORTED_TTS_MODEL.id, 'kokoro-v1.0.int8.onnx');
  assert.equal(SMALLEST_SUPPORTED_TTS_MODEL.quantization, 'int8');
  assert.ok(SMALLEST_SUPPORTED_TTS_MODEL.evidence.includes(
    'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend',
  ));
  assert.ok(
    TTS_MODEL_COMPATIBILITY.some((entry) => (
      entry.runtime === 'onnx'
      && entry.model === SMALLEST_SUPPORTED_TTS_MODEL.id
      && entry.compatible === true
    )),
    'the smallest declared variant must be represented as an ONNX-compatible table row',
  );
  assert.match(SMALLEST_SUPPORTED_TTS_MODEL.basis, /byte size is not recorded/);
});
