#!/usr/bin/env python3
"""Live side-panel viewer for the collab workspace.

Serves http://localhost:4517 — a dark chat panel that polls the shared
message log every 1.5s and shows live sessions, file claims, and the full
inter-session conversation as it happens. Started automatically when a
second session registers; safe to run manually too.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import collab_lib as cl

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Claude Collab — BetterFingers</title>
<style>
  :root { --bg:#0d1117; --panel:#161b22; --border:#30363d; --fg:#e6edf3; --dim:#8b949e;
          --urgent:#f85149; --question:#d29922; --handoff:#a371f7; --info:#58a6ff; --system:#3fb950; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--fg); font:14px/1.5 ui-monospace,monospace; height:100vh; display:flex; flex-direction:column; }
  header { padding:10px 16px; border-bottom:1px solid var(--border); display:flex; gap:12px; align-items:baseline; }
  header h1 { font-size:15px; }
  header .dot { color:var(--system); animation:pulse 2s infinite; }
  @keyframes pulse { 50% { opacity:.3 } }
  main { flex:1; display:flex; min-height:0; }
  #chat { flex:1; overflow-y:auto; padding:14px 16px; }
  aside { width:300px; border-left:1px solid var(--border); background:var(--panel); padding:14px; overflow-y:auto; }
  aside h2 { font-size:12px; text-transform:uppercase; color:var(--dim); margin:10px 0 6px; }
  .sess { padding:6px 8px; border:1px solid var(--border); border-radius:6px; margin-bottom:6px; }
  .sess b { color:var(--info); }
  .claim { font-size:12px; color:var(--dim); margin-bottom:4px; word-break:break-all; }
  .claim b { color:var(--handoff); }
  .msg { margin-bottom:10px; }
  .msg .meta { font-size:11px; color:var(--dim); }
  .msg .body { padding:8px 10px; border-radius:8px; background:var(--panel); border:1px solid var(--border); white-space:pre-wrap; word-break:break-word; }
  .k-urgent .body { border-color:var(--urgent); box-shadow:0 0 6px #f8514933; }
  .k-urgent .kind { color:var(--urgent); font-weight:bold; }
  .k-question .kind { color:var(--question); }
  .k-handoff .kind { color:var(--handoff); }
  .k-info .kind { color:var(--info); }
  .k-system .body { background:transparent; border:none; color:var(--system); font-style:italic; padding:0; }
  .empty { color:var(--dim); font-style:italic; margin-top:20px; text-align:center; }
</style></head><body>
<header><h1>Claude Collab Workspace</h1><span class="dot">●</span><span id="count" style="color:var(--dim)"></span></header>
<main>
  <div id="chat"><div class="empty">Waiting for messages…</div></div>
  <aside>
    <h2>Live sessions</h2><div id="sessions"></div>
    <h2>File claims</h2><div id="claims"></div>
  </aside>
</main>
<script>
const esc = s => s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const t = ts => new Date(ts*1000).toLocaleTimeString();
let lastLen = -1;
async function tick() {
  try {
    const r = await fetch('/api/state'); const d = await r.json();
    document.getElementById('count').textContent = Object.keys(d.sessions).length + ' session(s) live';
    document.getElementById('sessions').innerHTML = Object.values(d.sessions).map(s =>
      `<div class="sess"><b>${esc(s.name)}</b><br><span style="color:var(--dim)">${esc(s.focus)}</span></div>`
    ).join('') || '<div class="claim">none registered</div>';
    document.getElementById('claims').innerHTML = Object.entries(d.claims).map(([f,c]) =>
      `<div class="claim"><b>${esc(c.session)}</b> → ${esc(f)}<br>${esc(c.reason||'')}</div>`
    ).join('') || '<div class="claim">none</div>';
    if (d.messages.length !== lastLen) {
      lastLen = d.messages.length;
      const chat = document.getElementById('chat');
      const atBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 60;
      chat.innerHTML = d.messages.map(m =>
        `<div class="msg k-${esc(m.kind)}"><div class="meta">${t(m.ts)} <b>${esc(m.from)}</b> <span class="kind">[${esc(m.kind)}${m.to?' → '+esc(m.to):''}]</span></div><div class="body">${esc(m.text)}</div></div>`
      ).join('') || '<div class="empty">No messages yet</div>';
      if (atBottom) chat.scrollTop = chat.scrollHeight;
    }
  } catch(e) {}
}
tick(); setInterval(tick, 1500);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            body = json.dumps({
                "sessions": cl.get_sessions(),
                "claims": cl.get_claims(),
                "messages": cl.all_messages(),
            }).encode()
            ctype = "application/json"
        else:
            body = PAGE.encode()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", cl.VIEWER_PORT), Handler).serve_forever()
