#!/usr/bin/env python3
"""Claude Code Dashboard — dynamic server.
Reads memory files and session history on each request."""

import json
import os
import re
import html
import datetime
import hashlib
import secrets
import http.cookies
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, parse_qs

MEMORY_DIR = os.environ.get("MEMORY_DIR", "/root/MEMORY")
HISTORY_FILE = os.environ.get("HISTORY_FILE", "/root/.claude/history.jsonl")
BIND = os.environ.get("BIND", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))

# ── Auth ──
AUTH_USER = os.environ.get("AUTH_USER", "admin")
AUTH_PASS = os.environ.get("AUTH_PASS", "changeme")
SESSION_SECRET = secrets.token_hex(32)
# Valid session tokens (in-memory, survive until restart)
valid_sessions = set()


def make_session_token(user):
    token = secrets.token_hex(32)
    valid_sessions.add(token)
    return token


def check_session(cookie_header):
    if not cookie_header:
        return False
    c = http.cookies.SimpleCookie()
    try:
        c.load(cookie_header)
    except:
        return False
    morsel = c.get("session")
    if morsel and morsel.value in valid_sessions:
        return True
    return False


def norm_path(p):
    """Normalize Windows/UNC paths to POSIX. Override via NORM_PATH_MAP env var.
    Format: 'from1=to1,from2=to2' e.g. 'C:/Users/me=/home/me,//server/share=/mnt/share'"""
    if not p:
        return ""
    p = p.replace("\\\\", "/").replace("\\", "/")
    for mapping in os.environ.get("NORM_PATH_MAP", "").split(","):
        if "=" in mapping:
            src, dst = mapping.split("=", 1)
            if src and p.startswith(src):
                p = dst + p[len(src):]
                return p
    # Default: strip Windows drive letter prefix
    m = re.match(r'^[A-Z]:/(.+)', p, re.I)
    if m:
        return "/" + m.group(1)
    return p


def md_to_html(text):
    text = html.escape(text)
    text = re.sub(r'^### (.+)$', r'<h4>\1</h4>', text, flags=re.M)
    text = re.sub(r'^## (.+)$', r'<h3>\1</h3>', text, flags=re.M)
    text = re.sub(r'^# (.+)$', r'<h2>\1</h2>', text, flags=re.M)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'```(\w*)\n(.*?)```', lambda m: f'<pre><code>{m.group(2)}</code></pre>', text, flags=re.S)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+\.md)\)', r'<a href="#" onclick="showFile(\'\2\');return false">\1</a>', text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)
    text = re.sub(r'^- (.+)$', r'<li>\1</li>', text, flags=re.M)
    text = re.sub(r'(<li>.*?</li>)', r'<ul>\1</ul>', text, flags=re.S)
    text = text.replace('</ul>\n<ul>', '\n')
    text = re.sub(r'\n\n+', '</p><p>', text)
    return f"<p>{text}</p>"


def parse_frontmatter(content):
    meta = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = parts[2].strip()
    return meta, body


def build_memory_page():
    files = {}
    for fname in sorted(os.listdir(MEMORY_DIR)):
        if not fname.endswith(".md"):
            continue
        with open(os.path.join(MEMORY_DIR, fname)) as f:
            files[fname] = f.read()

    entries = []
    for fname, content in files.items():
        if fname in ("MEMORY.md", "00-index.md"):
            continue
        meta, body = parse_frontmatter(content)
        entries.append({
            "fname": fname,
            "name": meta.get("name", fname.replace(".md", "").replace("-", " ").title()),
            "type": meta.get("type", ""),
            "description": meta.get("description", ""),
            "html": md_to_html(body),
            "raw": content,
        })

    index_content = files.get("MEMORY.md", "")
    file_data = {}
    for e in entries:
        file_data[e["fname"]] = {"name": e["name"], "type": e["type"], "description": e["description"], "html": e["html"], "raw": e["raw"]}
    file_data["MEMORY.md"] = {"name": "MEMORY Index", "type": "index", "description": "Main index", "html": md_to_html(index_content), "raw": index_content}

    type_colors = {"user": "#58a6ff", "feedback": "#f0883e", "project": "#7ee787", "reference": "#d2a8ff", "": "#8b949e"}
    type_labels = {"user": "👤 User", "feedback": "💬 Feedback", "project": "📁 Projects", "reference": "📌 Reference", "other": "📄 Other"}

    by_type = {}
    for e in entries:
        by_type.setdefault(e["type"] or "other", []).append(e)

    sidebar_html = ""
    for t in ["user", "feedback", "project", "reference", "other"]:
        items = by_type.get(t, [])
        if not items:
            continue
        color = type_colors.get(t, "#8b949e")
        sidebar_html += f'<div class="sidebar-group"><div class="sidebar-group-title" style="color:{color}">{type_labels.get(t, t)}</div>'
        for e in items:
            sidebar_html += f'<div class="sidebar-item" onclick="showFile(\'{e["fname"]}\')" data-file="{e["fname"]}" title="{html.escape(e["description"])}">{html.escape(e["name"])}</div>'
        sidebar_html += '</div>'

    counts = {t: len(v) for t, v in by_type.items()}
    total = len(entries)

    return MEMORY_TEMPLATE.format(
        total=total,
        sidebar_html=sidebar_html,
        file_data_json=json.dumps(file_data, ensure_ascii=False),
        type_colors_json=json.dumps(type_colors),
        cnt_user=counts.get("user", 0),
        cnt_feedback=counts.get("feedback", 0),
        cnt_project=counts.get("project", 0),
        cnt_reference=counts.get("reference", 0),
        cnt_other=counts.get("other", 0),
    )


def build_sessions_page():
    from collections import OrderedDict
    sessions = OrderedDict()
    with open(HISTORY_FILE) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
            except:
                continue
            sid = entry.get("sessionId", "")
            if not sid:
                continue
            ts = entry.get("timestamp", 0)
            if sid not in sessions:
                sessions[sid] = {"messages": [], "project": entry.get("project", ""), "first_ts": ts, "last_ts": ts, "last_msg": ""}
            sessions[sid]["last_ts"] = max(sessions[sid]["last_ts"], ts)
            msg = entry.get("display", "").strip()
            if msg and msg not in ("/init", "/usage"):
                sessions[sid]["last_msg"] = msg
                sessions[sid]["messages"].append(msg)

    rows = []
    for sid, info in sessions.items():
        msgs = info["messages"]
        if not msgs:
            continue
        theme = msgs[0][:120]
        preview = " → ".join(m[:80] for m in msgs[:5])
        raw_project = info["project"]
        project_name = raw_project.replace("\\\\", "/").replace("\\", "/").split("/")[-1] if raw_project else "—"
        project_path = norm_path(raw_project)
        dt = datetime.datetime.fromtimestamp(info["first_ts"] / 1000).strftime("%Y-%m-%d %H:%M")
        dt_last = datetime.datetime.fromtimestamp(info["last_ts"] / 1000).strftime("%Y-%m-%d %H:%M")
        last_msg = info["last_msg"][:120]
        all_msgs = "\n".join(msgs)
        rows.append((sid, theme, preview, project_name, project_path, dt, dt_last, last_msg, all_msgs))

    rows.sort(key=lambda r: r[6], reverse=True)

    search_index = {}
    session_msgs = {}
    html_rows = ""
    for i, (sid, theme, preview, project_name, project_path, dt, dt_last, last_msg, all_msgs) in enumerate(rows):
        cmd = f"claude --resume {sid}"
        cd_cmd = f"cd {project_path}" if project_path else ""
        full_cmd = f"{cd_cmd} && {cmd}" if cd_cmd else cmd
        search_index[i] = all_msgs
        session_msgs[i] = all_msgs.split("\n")
        html_rows += f"""
    <tr data-idx="{i}" onclick="openSession({i})" style="cursor:pointer">
      <td class="num">{i + 1}</td>
      <td class="date">{html.escape(dt)}</td>
      <td class="date">{html.escape(dt_last)}</td>
      <td class="project">{html.escape(project_name)}</td>
      <td class="theme" title="{html.escape(preview)}">{html.escape(theme)}</td>
      <td class="last-msg" title="{html.escape(last_msg)}">{html.escape(last_msg)}</td>
      <td class="cmd" onclick="event.stopPropagation()">
        <code id="cmd-{i}">{html.escape(full_cmd)}</code>
        <button onclick="copyCmd('cmd-{i}')" title="Copy">📋</button>
      </td>
    </tr>"""

    return (SESSIONS_TEMPLATE
        .replace("{count}", str(len(rows)))
        .replace("{rows}", html_rows)
        .replace("{search_index}", json.dumps(search_index, ensure_ascii=False))
        .replace("{session_msgs}", json.dumps(session_msgs, ensure_ascii=False)))


# ── Floating Nav (shared) ──
FLOATING_NAV = """
<style>
.fnav{position:fixed;top:16px;left:50%;transform:translateX(-50%);display:flex;gap:6px;z-index:1000}
.fnav a{display:flex;align-items:center;gap:6px;padding:8px 14px;background:#161b22;border:1px solid #30363d;border-radius:8px;color:#8b949e;text-decoration:none;font-size:.82em;font-weight:500;transition:all .2s;backdrop-filter:blur(10px);background:rgba(22,27,34,.85)}
.fnav a:hover{border-color:#58a6ff;color:#58a6ff;transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.3)}
.fnav a.active{border-color:#58a6ff;color:#58a6ff;background:rgba(31,111,235,.12)}
.fnav .icon{font-size:1.1em}
</style>
<nav class="fnav">
<a href="/" class="NAV_HOME"><span class="icon">🏠</span>Home</a>
<a href="/memory" class="NAV_MEMORY"><span class="icon">🧠</span>Memory</a>
<a href="/sessions" class="NAV_SESSIONS"><span class="icon">💬</span>Sessions</a>
<a href="/logout"><span class="icon">🚪</span>Logout</a>
</nav>
"""

def nav(active="home"):
    return (FLOATING_NAV
        .replace("NAV_HOME", "active" if active == "home" else "")
        .replace("NAV_MEMORY", "active" if active == "memory" else "")
        .replace("NAV_SESSIONS", "active" if active == "sessions" else ""))


# ── Templates ──

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Claude Code Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;min-height:100vh}
.container{max-width:600px;width:100%;padding:40px 20px}
h1{color:#f0f6fc;font-size:2em;margin-bottom:6px}
.subtitle{color:#484f58;margin-bottom:32px;font-size:.95em}
.cards{display:flex;flex-direction:column;gap:16px}
a.card{display:flex;align-items:center;gap:20px;background:#161b22;border:1px solid #21262d;border-radius:12px;padding:24px;text-decoration:none;color:inherit;transition:all .2s}
a.card:hover{border-color:#58a6ff;background:#1c2129;transform:translateY(-2px);box-shadow:0 4px 20px #00000040}
.card-icon{font-size:2.4em;min-width:56px;text-align:center}
.card-text h2{font-size:1.15em;color:#f0f6fc;margin-bottom:4px}
.card-text p{font-size:.85em;color:#8b949e;line-height:1.4}
.footer{margin-top:40px;text-align:center;color:#30363d;font-size:.8em}
</style></head><body>
<div class="container">
<h1>Claude Code</h1>
<p class="subtitle">Dashboard</p>
<div class="cards">
  <a class="card" href="/memory"><div class="card-icon">🧠</div><div class="card-text"><h2>Memory</h2><p>Knowledge base — user, servers, projects, feedback, references</p></div></a>
  <a class="card" href="/sessions"><div class="card-icon">💬</div><div class="card-text"><h2>Sessions</h2><p>All conversations with cd + resume commands</p></div></a>
</div>
</div></body></html>"""

MEMORY_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Claude Memory</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;height:100vh;overflow:hidden}}
.sidebar{{width:280px;min-width:280px;background:#010409;border-right:1px solid #21262d;display:flex;flex-direction:column;overflow:hidden}}
.sidebar-header{{padding:16px;border-bottom:1px solid #21262d}}
.sidebar-header h1{{font-size:1.2em;color:#58a6ff;margin-bottom:4px}}
.sidebar-header .stats{{font-size:.75em;color:#484f58}}
.sidebar-search{{padding:8px 12px;border-bottom:1px solid #21262d}}
.sidebar-search input{{width:100%;padding:6px 10px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:.85em;outline:none}}
.sidebar-search input:focus{{border-color:#58a6ff}}
.sidebar-list{{flex:1;overflow-y:auto;padding:8px 0}}
.sidebar-group{{margin-bottom:4px}}
.sidebar-group-title{{padding:6px 16px 4px;font-size:.7em;font-weight:700;text-transform:uppercase;letter-spacing:.05em}}
.sidebar-item{{padding:6px 16px 6px 24px;font-size:.85em;cursor:pointer;transition:background .15s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.sidebar-item:hover{{background:#161b22}}
.sidebar-item.active{{background:#1f6feb22;color:#58a6ff;border-right:2px solid #58a6ff}}
.main{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
.topbar{{padding:12px 24px;border-bottom:1px solid #21262d;display:flex;align-items:center;gap:12px;background:#010409}}
.topbar .file-name{{font-size:1.1em;font-weight:600;color:#f0f6fc}}
.topbar .file-type{{font-size:.75em;padding:2px 8px;border-radius:12px;font-weight:600}}
.topbar .file-desc{{font-size:.85em;color:#8b949e;margin-left:auto}}
.topbar .view-toggle{{margin-left:12px;display:flex;gap:2px}}
.topbar .view-toggle button{{background:#21262d;border:none;color:#8b949e;padding:4px 10px;cursor:pointer;font-size:.8em}}
.topbar .view-toggle button:first-child{{border-radius:4px 0 0 4px}}
.topbar .view-toggle button:last-child{{border-radius:0 4px 4px 0}}
.topbar .view-toggle button.active{{background:#1f6feb;color:#fff}}
.content{{flex:1;overflow-y:auto;padding:24px 32px}}
.content h2{{color:#f0f6fc;border-bottom:1px solid #21262d;padding-bottom:8px;margin:16px 0 12px}}
.content h3{{color:#d2a8ff;margin:14px 0 8px}}
.content h4{{color:#7ee787;margin:10px 0 6px}}
.content p{{margin:6px 0;line-height:1.6}}
.content ul{{margin:6px 0 6px 20px}}
.content li{{margin:3px 0;line-height:1.5}}
.content code{{background:#1c2129;padding:1px 6px;border-radius:3px;font-family:'Cascadia Code','Fira Code',monospace;font-size:.9em;color:#7ee787}}
.content pre{{background:#161b22;padding:12px 16px;border-radius:6px;overflow-x:auto;margin:8px 0;border:1px solid #21262d}}
.content pre code{{background:none;padding:0;color:#c9d1d9}}
.content a{{color:#58a6ff;text-decoration:none}}
.content a:hover{{text-decoration:underline}}
.content strong{{color:#f0f6fc}}
.raw-view{{white-space:pre-wrap;font-family:'Cascadia Code','Fira Code',monospace;font-size:.85em;color:#8b949e}}
.welcome{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#484f58}}
.welcome h2{{font-size:1.8em;color:#30363d;margin-bottom:8px}}
.stats-row{{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}}
.stat-card{{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 16px;min-width:120px}}
.stat-card .num{{font-size:1.6em;font-weight:700}}
.stat-card .label{{font-size:.75em;color:#8b949e;margin-top:2px}}
.sidebar-list::-webkit-scrollbar,.content::-webkit-scrollbar{{width:6px}}
.sidebar-list::-webkit-scrollbar-thumb,.content::-webkit-scrollbar-thumb{{background:#30363d;border-radius:3px}}
</style></head><body>
<div class="sidebar">
<div class="sidebar-header"><h1>🧠 Claude Memory</h1><div class="stats">{total} memories</div></div>
<div class="sidebar-search"><input type="text" placeholder="Search..." oninput="filterSidebar(this.value)"></div>
<div class="sidebar-list">
<div class="sidebar-item" onclick="showFile('MEMORY.md')" data-file="MEMORY.md" style="color:#58a6ff;font-weight:600">📋 Index (MEMORY.md)</div>
{sidebar_html}
</div></div>
<div class="main">
<div class="topbar" id="topbar" style="display:none">
<span class="file-name" id="topFileName"></span>
<span class="file-type" id="topFileType"></span>
<span class="file-desc" id="topFileDesc"></span>
<div class="view-toggle">
<button id="btnRendered" class="active" onclick="setView('rendered')">Rendered</button>
<button id="btnRaw" onclick="setView('raw')">Raw</button>
</div></div>
<div class="content" id="content">
<div class="welcome"><h2>🧠 Claude Memory</h2><p>Select a memory file from the sidebar</p><br>
<div class="stats-row">
<div class="stat-card"><div class="num" style="color:#58a6ff">{total}</div><div class="label">Total</div></div>
<div class="stat-card"><div class="num" style="color:#58a6ff">{cnt_user}</div><div class="label">User</div></div>
<div class="stat-card"><div class="num" style="color:#f0883e">{cnt_feedback}</div><div class="label">Feedback</div></div>
<div class="stat-card"><div class="num" style="color:#7ee787">{cnt_project}</div><div class="label">Projects</div></div>
<div class="stat-card"><div class="num" style="color:#d2a8ff">{cnt_reference}</div><div class="label">Reference</div></div>
<div class="stat-card"><div class="num" style="color:#8b949e">{cnt_other}</div><div class="label">Other</div></div>
</div></div></div></div>
<script>
const FILES={file_data_json};
const TYPE_COLORS={type_colors_json};
let currentView='rendered',currentFile=null;
function showFile(fname){{const f=FILES[fname];if(!f)return;currentFile=fname;document.getElementById('topbar').style.display='flex';document.getElementById('topFileName').textContent=f.name;const t=document.getElementById('topFileType');t.textContent=f.type||'file';t.style.background=(TYPE_COLORS[f.type]||'#8b949e')+'22';t.style.color=TYPE_COLORS[f.type]||'#8b949e';document.getElementById('topFileDesc').textContent=f.description;renderContent();document.querySelectorAll('.sidebar-item').forEach(el=>el.classList.toggle('active',el.dataset.file===fname))}}
function renderContent(){{const f=FILES[currentFile],el=document.getElementById('content');if(currentView==='rendered'){{el.innerHTML=f.html;el.classList.remove('raw-view')}}else{{el.textContent=f.raw;el.classList.add('raw-view')}}}}
function setView(v){{currentView=v;document.getElementById('btnRendered').classList.toggle('active',v==='rendered');document.getElementById('btnRaw').classList.toggle('active',v==='raw');if(currentFile)renderContent()}}
function filterSidebar(q){{q=q.toLowerCase();document.querySelectorAll('.sidebar-item').forEach(el=>{{const fname=el.dataset.file;const f=FILES[fname];const text=(f?f.name+' '+f.description+' '+f.raw:el.textContent).toLowerCase();el.style.display=text.includes(q)?'':'none'}});document.querySelectorAll('.sidebar-group').forEach(g=>{{g.style.display=g.querySelectorAll('.sidebar-item:not([style*="display: none"])').length?'':'none'}})}}
</script></body></html>"""

SESSIONS_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Claude Sessions</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:20px}
h1{color:#58a6ff;margin-bottom:6px;font-size:1.6em}
.subtitle{color:#8b949e;margin-bottom:16px;font-size:.9em}
table{width:100%;border-collapse:collapse;font-size:.85em}
th{background:#161b22;color:#58a6ff;padding:10px 8px;text-align:left;position:sticky;top:0;cursor:pointer;user-select:none;border-bottom:2px solid #30363d}
th:hover{background:#1c2129}
td{padding:8px;border-bottom:1px solid #21262d;vertical-align:top}
tr:hover{background:#1c2129}
.num{width:30px;color:#484f58;text-align:center}
.date{width:120px;white-space:nowrap;color:#8b949e;font-size:.9em}
.project{width:100px;color:#d2a8ff;font-weight:500}
.theme{max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.last-msg{max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#8b949e;font-size:.9em}
.cmd{white-space:nowrap}
.cmd code{background:#1c2129;padding:3px 8px;border-radius:4px;font-family:'Cascadia Code','Fira Code',monospace;font-size:.85em;color:#7ee787;display:inline-block;max-width:480px;overflow:hidden;text-overflow:ellipsis;vertical-align:middle}
.cmd button{background:none;border:1px solid #30363d;border-radius:4px;cursor:pointer;padding:2px 6px;margin-left:4px;font-size:.9em;transition:all .2s;vertical-align:middle}
.cmd button:hover{background:#238636;border-color:#238636}
.search{width:100%;padding:10px 14px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:.95em;margin-bottom:12px;outline:none}
.search:focus{border-color:#58a6ff}
.toast{position:fixed;bottom:20px;right:20px;background:#238636;color:#fff;padding:10px 20px;border-radius:6px;display:none;font-size:.9em;z-index:999}
.drawer-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:999;display:none}
.drawer{position:fixed;top:0;right:-50%;width:50%;height:100%;background:#0d1117;border-left:1px solid #30363d;z-index:1000;transition:right .3s ease;display:flex;flex-direction:column}
.drawer.open{right:0}
.drawer-header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #21262d;background:#161b22;flex-shrink:0}
.drawer-header h2{font-size:1em;color:#f0f6fc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80%}
.drawer-header .meta{font-size:.78em;color:#8b949e;margin-top:2px}
.drawer-close{background:none;border:none;color:#8b949e;font-size:1.4em;cursor:pointer;padding:4px 8px;border-radius:4px;flex-shrink:0}
.drawer-close:hover{background:#21262d;color:#f0f6fc}
.drawer-body{flex:1;overflow-y:auto;padding:0}
.msg{padding:12px 20px;border-bottom:1px solid #21262d;font-size:.88em;line-height:1.6;word-wrap:break-word;white-space:pre-wrap}
.msg:hover{background:#161b22}
.msg-num{color:#484f58;font-size:.75em;margin-right:8px;user-select:none}
.drawer-body::-webkit-scrollbar{width:6px}
.drawer-body::-webkit-scrollbar-thumb{background:#30363d;border-radius:3px}
.search-match{background:rgba(88,166,255,.15)}
.highlight{background:#58a6ff33;color:#fff;border-radius:2px;padding:0 2px}
@media(max-width:900px){.drawer{width:85%;right:-85%}}
</style></head><body>
<h1>Claude Code Sessions</h1>
<p class="subtitle">{count} sessions — click row to view, 📋 to copy command</p>
<input class="search" type="text" placeholder="🔍 Full-text search across all messages..." oninput="filterRows(this.value)" id="searchInput">
<table><thead><tr>
<th>#</th><th onclick="sortTable(1)">Start ▼</th><th onclick="sortTable(2)">Last</th><th onclick="sortTable(3)">Project</th><th onclick="sortTable(4)">First message</th><th onclick="sortTable(5)">Last message</th><th>Command</th>
</tr></thead><tbody id="tbody">{rows}</tbody></table>
<div class="toast" id="toast">Copied!</div>
<div class="drawer-overlay" id="overlay" onclick="closeDrawer()"></div>
<div class="drawer" id="drawer">
<div class="drawer-header">
<div><h2 id="drawerTitle"></h2><div class="meta" id="drawerMeta"></div></div>
<button class="drawer-close" onclick="closeDrawer()">&times;</button>
</div>
<div class="drawer-body" id="drawerBody"></div>
</div>
<script>
const SI={search_index};
const SM={session_msgs};
function copyCmd(id){const text=document.getElementById(id).textContent;navigator.clipboard.writeText(text).then(()=>{const btn=document.getElementById(id).nextElementSibling;btn.textContent='✅';const toast=document.getElementById('toast');toast.style.display='block';setTimeout(()=>{toast.style.display='none';btn.textContent='📋'},1500)})}
function filterRows(q){q=q.toLowerCase();document.querySelectorAll('#tbody tr').forEach(tr=>{const idx=tr.dataset.idx;const allText=SI[idx]||'';const visible=!q||allText.toLowerCase().includes(q)||tr.textContent.toLowerCase().includes(q);tr.style.display=visible?'':'none';tr.classList.toggle('search-match',!!q&&visible)})}
let sortDir={};
function sortTable(col){const tbody=document.getElementById('tbody');const rows=Array.from(tbody.rows);sortDir[col]=!sortDir[col];rows.sort((a,b)=>{let va=a.cells[col].textContent.trim(),vb=b.cells[col].textContent.trim();return sortDir[col]?va.localeCompare(vb):vb.localeCompare(va)});rows.forEach(r=>tbody.appendChild(r))}
function openSession(idx){const msgs=SM[idx]||[];const tr=document.querySelector('tr[data-idx="'+idx+'"]');const project=tr?tr.cells[3].textContent:'';const dateStart=tr?tr.cells[1].textContent:'';const dateEnd=tr?tr.cells[2].textContent:'';document.getElementById('drawerTitle').textContent=msgs[0]?msgs[0].substring(0,100):'Session';document.getElementById('drawerMeta').textContent=project+' | '+dateStart+' — '+dateEnd+' | '+msgs.length+' messages';const q=document.getElementById('searchInput').value.toLowerCase();const body=document.getElementById('drawerBody');body.innerHTML=msgs.map((m,i)=>{let t=escHtml(m);if(q)t=t.replace(new RegExp('('+escRe(q)+')','gi'),'<span class="highlight">$1</span>');return '<div class="msg"><span class="msg-num">#'+(i+1)+'</span>'+t+'</div>'}).join('');document.getElementById('drawer').classList.add('open');document.getElementById('overlay').style.display='block';if(q){setTimeout(()=>{const first=body.querySelector('.highlight');if(first)first.scrollIntoView({block:'center'})},100)}}
function closeDrawer(){document.getElementById('drawer').classList.remove('open');document.getElementById('overlay').style.display='none'}
function escHtml(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function escRe(s){return s.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer()})
</script></body></html>"""


LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Login — Claude Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;min-height:100vh}
.login-box{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:40px;width:360px}
h1{color:#58a6ff;font-size:1.4em;margin-bottom:24px;text-align:center}
label{display:block;font-size:.85em;color:#8b949e;margin-bottom:4px}
input[type=text],input[type=password]{width:100%;padding:10px 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:.95em;margin-bottom:16px;outline:none}
input:focus{border-color:#58a6ff}
button{width:100%;padding:10px;background:#238636;border:none;border-radius:6px;color:#fff;font-size:1em;cursor:pointer;font-weight:600}
button:hover{background:#2ea043}
.error{color:#f85149;font-size:.85em;text-align:center;margin-bottom:12px}
</style></head><body>
<form class="login-box" method="POST" action="/login">
<h1>🔒 Claude Dashboard</h1>
<!--ERROR-->
<label>User</label><input type="text" name="user" autofocus>
<label>Password</label><input type="password" name="pass">
<button type="submit">Login</button>
</form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def is_authenticated(self):
        return check_session(self.headers.get("Cookie"))

    def do_GET(self):
        path = unquote(self.path).split("?")[0].rstrip("/") or "/"
        if path == "/login":
            self.respond(200, "text/html", LOGIN_TEMPLATE.replace("<!--ERROR-->", ""))
            return
        if path == "/logout":
            cookie = http.cookies.SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                token = cookie.get("session")
                if token:
                    valid_sessions.discard(token.value)
            except:
                pass
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0")
            self.end_headers()
            return
        if not self.is_authenticated():
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if path == "/":
            self.respond(200, "text/html", INDEX_TEMPLATE.replace("</body>", nav("home") + "</body>"))
        elif path == "/memory":
            self.respond(200, "text/html", build_memory_page().replace("</body>", nav("memory") + "</body>"))
        elif path == "/sessions":
            self.respond(200, "text/html", build_sessions_page().replace("</body>", nav("sessions") + "</body>"))
        else:
            self.respond(404, "text/html", "<h1>404</h1>")

    def do_POST(self):
        path = unquote(self.path).rstrip("/") or "/"
        if path == "/login":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body)
            user = params.get("user", [""])[0]
            passwd = params.get("pass", [""])[0]
            if user == AUTH_USER and passwd == AUTH_PASS:
                token = make_session_token(user)
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"session={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=604800")
                self.end_headers()
            else:
                self.respond(200, "text/html", LOGIN_TEMPLATE.replace("<!--ERROR-->",
                    '<div class="error">Wrong username or password</div>'))
            return
        self.respond(405, "text/html", "<h1>405</h1>")

    def respond(self, code, content_type, body, extra_headers=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # silent


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    USE_SSL = os.environ.get("USE_SSL", "1") == "1"
    server = ThreadedHTTPServer((BIND, PORT), Handler)
    if USE_SSL:
        import ssl
        CERT = os.environ.get("CERT_FILE", "cert.pem")
        KEY = os.environ.get("KEY_FILE", "key.pem")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT, KEY)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        print(f"Claude Dashboard running on https://{BIND}:{PORT}")
    else:
        print(f"Claude Dashboard running on http://{BIND}:{PORT}")
    server.serve_forever()
