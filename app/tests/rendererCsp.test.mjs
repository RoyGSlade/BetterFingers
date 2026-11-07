// Phase 0 item 6: a strict CSP on every page the app can load.
// Run with: node --test app/tests/rendererCsp.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const RENDERER = path.resolve(HERE, '..', 'src', 'renderer');
const { RENDERER_CSP } = require('../src/main/sessionSecurity.js');
const { RENDERER_PAGES } = require('../src/main/senderValidation.js');

// --- CSP on every page -------------------------------------------------------

function directives(policy) {
  return Object.fromEntries(
    policy.split(';').map((part) => part.trim()).filter(Boolean).map((part) => {
      const [name, ...values] = part.split(/\s+/);
      return [name, values];
    }),
  );
}

test('the policy itself has no inline or remote script and no network', () => {
  const d = directives(RENDERER_CSP);
  assert.deepEqual(d['default-src'], ["'none'"]);
  assert.deepEqual(d['script-src'], ["'self'"]);
  assert.deepEqual(d['connect-src'], ["'none'"]);
  assert.deepEqual(d['object-src'], ["'none'"]);
  assert.deepEqual(d['frame-src'], ["'none'"]);
  assert.deepEqual(d['base-uri'], ["'none'"]);
  assert.deepEqual(d['form-action'], ["'none'"]);
  assert.ok(!RENDERER_CSP.includes('http'), 'no remote origin anywhere in the policy');
  assert.ok(!RENDERER_CSP.includes('*'), 'no wildcard');
  assert.ok(!d['script-src'].includes("'unsafe-inline'") && !d['script-src'].includes("'unsafe-eval'"));
});

test('every page the app can load carries exactly that policy in a meta tag', () => {
  assert.ok(RENDERER_PAGES.size >= 6);
  for (const page of RENDERER_PAGES) {
    const html = fs.readFileSync(path.join(RENDERER, page), 'utf8');
    const metas = [...html.matchAll(/<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"/g)];
    assert.equal(metas.length, 1, `${page} must have exactly one CSP meta tag`);
    assert.equal(metas[0][1], RENDERER_CSP, `${page} must carry the shared policy verbatim`);
  }
});

// Drops HTML comments the way the parser reads them: a comment runs from "<!--" to the first
// "-->", and an unterminated one runs to the end. One left-to-right pass, so text outside a
// comment is never reinterpreted (a regex replace can splice a new "<!--" out of the pieces).
function stripHtmlComments(html) {
  let out = '';
  let at = 0;
  for (;;) {
    const start = html.indexOf('<!--', at);
    if (start === -1) return out + html.slice(at);
    out += html.slice(at, start);
    const end = html.indexOf('-->', start + 4);
    if (end === -1) return out;
    at = end + 3;
  }
}

test('stripHtmlComments keeps everything outside comments and nothing inside them', () => {
  assert.equal(stripHtmlComments('a<!-- x -->b<!--y-->c'), 'abc');
  assert.equal(stripHtmlComments('a<!-- <script>x</script> -->b'), 'ab');
  assert.equal(stripHtmlComments('a<!-- unterminated <script>'), 'a');
  assert.equal(stripHtmlComments('<script src="x.js"></script>'), '<script src="x.js"></script>');
});

test('no page has an inline classic script, an inline event handler or a remote script', () => {
  for (const page of RENDERER_PAGES) {
    const html = stripHtmlComments(fs.readFileSync(path.join(RENDERER, page), 'utf8'));
    for (const m of html.matchAll(/<script\b([^>]*)>/gi)) {
      const attrs = m[1];
      const src = /\bsrc="([^"]*)"/.exec(attrs)?.[1];
      const isModule = /\btype="module"/.test(attrs);
      assert.ok(src || isModule, `${page}: inline classic <script> is blocked by the CSP`);
      if (src) assert.ok(!/^[a-z]+:/i.test(src) && !src.startsWith('//'), `${page}: remote script ${src}`);
    }
    assert.ok(!/\son[a-z]+\s*=\s*["']/i.test(html), `${page}: inline event-handler attribute`);
    assert.ok(!/javascript:/i.test(html), `${page}: javascript: URL`);
  }
});

test('the renderer never opens a network connection itself', () => {
  // connect-src is 'none', so a stray fetch/XHR/WebSocket would silently die.
  const offenders = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) { if (entry.name !== 'vendor') walk(full); continue; }
      if (!/\.(m?js)$/.test(entry.name)) continue;
      const text = fs.readFileSync(full, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
      if (/\b(fetch|XMLHttpRequest|EventSource)\s*\(|new\s+WebSocket\s*\(/.test(text)) offenders.push(path.relative(RENDERER, full));
    }
  };
  walk(RENDERER);
  assert.deepEqual(offenders, []);
});
