import os
import sys
import glob
import json
import time
import re
import sqlite3
import subprocess
import urllib.request
from datetime import datetime

def format_tokens(num):
    if num is None:
        return "0"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}k"
    return str(num)

def parse_iso(ts_str):
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_str)
        return dt.timestamp()
    except Exception:
        return None

# ==============================================================================
# FAST CACHED HUB CLIENT (ANTIGRAVITY)
# ==============================================================================
HUB_CACHE_FILE = os.path.expanduser("~/.config/herdr-app/data/.hub_cache.json")

def read_hub_cache():
    if os.path.isfile(HUB_CACHE_FILE):
        try:
            with open(HUB_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def write_hub_cache(port, csrf):
    try:
        os.makedirs(os.path.dirname(HUB_CACHE_FILE), exist_ok=True)
        with open(HUB_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"port": port, "csrf": csrf}, f)
    except Exception:
        pass

def query_hub_endpoint(port, csrf):
    url = f"http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-Codeium-Csrf-Token": csrf,
            "Connect-Protocol-Version": "1"
        }
    )
    with urllib.request.urlopen(req, timeout=1.5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        groups = data.get("response", {}).get("groups", [])
        result = {}
        for g in groups:
            for b in g.get("buckets", []):
                bid = b.get("bucketId")
                result[bid] = {
                    "percent_remaining": round(b.get("remainingFraction", 0) * 100, 1),
                    "reset_time": b.get("resetTime")
                }
        return result

def get_live_antigravity_quotas():
    cached = read_hub_cache()
    if cached and "port" in cached and "csrf" in cached:
        try:
            return query_hub_endpoint(cached["port"], cached["csrf"])
        except Exception:
            pass

    line = ""
    try:
        if sys.platform == "win32":
            ps_cmd = "(Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*agy*' -and $_.CommandLine -like '*--hub-port*' }).CommandLine"
            cmd = ["powershell", "-NoProfile", "-Command", ps_cmd]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            line = res.stdout or ""
        else:
            # macOS / Linux process listing
            for ps_args in [["ps", "-eo", "args"], ["ps", "aux"]]:
                try:
                    res = subprocess.run(ps_args, capture_output=True, text=True, timeout=2)
                    for l in (res.stdout or "").split("\n"):
                        if "agy" in l and "--hub-port" in l:
                            line = l
                            break
                    if line:
                        break
                except Exception:
                    pass
    except Exception:
        pass

    if line:
        m_port = re.search(r"--hub-port=(\d+)", line)
        m_csrf = re.search(r"--csrf_token=([a-zA-Z0-9\-]+)", line)
        if m_port and m_csrf:
            port = m_port.group(1)
            csrf = m_csrf.group(1)
            write_hub_cache(port, csrf)
            return query_hub_endpoint(port, csrf)

    return None

import unicodedata

def clean_txt(s):
    if not s:
        return ""
    n = unicodedata.normalize("NFD", s)
    return "".join(c for c in n if unicodedata.category(c) != "Mn").lower()

def get_antigravity_db_paths():
    candidates = [
        os.path.expanduser("~/.gemini/antigravity-cli/conversation_summaries.db"),
        os.path.expanduser("~/.gemini/antigravity/conversation_summaries.db"),
        os.path.expanduser("~/Library/Application Support/antigravity-cli/conversation_summaries.db"),
        os.path.expanduser("~/Library/Application Support/Google/antigravity-cli/conversation_summaries.db"),
        os.path.expanduser("~/.local/share/antigravity-cli/conversation_summaries.db"),
        os.path.expanduser("~/.config/antigravity-cli/conversation_summaries.db")
    ]
    if os.environ.get("ANTIGRAVITY_DATA_DIR"):
        candidates.insert(0, os.path.join(os.environ["ANTIGRAVITY_DATA_DIR"], "conversation_summaries.db"))
    return [p for p in candidates if os.path.isfile(p)]

def find_conversation(target_cwd, session_hint=None, screen_snippet=None):
    db_paths = get_antigravity_db_paths()
    snip_norm = clean_txt(screen_snippet)

    # 1. Exact hint match if hint is a real id or title (and not an executable path)
    if session_hint and not session_hint.lower().endswith(".exe") and not "powershell" in session_hint.lower() and not "pwsh" in session_hint.lower():
        for db_path in db_paths:
            if not os.path.isfile(db_path):
                continue
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT conversation_id, workspace_uris, app_data_dir, title
                    FROM conversation_summaries
                    WHERE conversation_id = ? OR LOWER(title) = ? OR LOWER(title) LIKE ?
                    LIMIT 1
                """, (session_hint, session_hint.lower(), f"%{session_hint.lower()}%"))
                r = cursor.fetchone()
                conn.close()
                if r:
                    return r[0], r[2], r[3]
            except Exception:
                pass

    # 2. Extract search chunks from screen_snippet
    words = snip_norm.split()
    chunks = []
    for i in range(len(words) - 3):
        chunk = " ".join(words[i:i+4])
        if len(chunk) >= 12:
            chunks.append(chunk)

    best_cid, best_dir, best_title = None, "antigravity-cli", None
    best_score = -1

    for db_path in db_paths:
        if not os.path.isfile(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT conversation_id, workspace_uris, app_data_dir, title FROM conversation_summaries ORDER BY last_modified_time DESC LIMIT 30")
            rows = c.fetchall()
            conn.close()

            for cid, uris, app_dir, title in rows:
                score = 0
                
                # Check workspace URI match specificity
                if uris:
                    try:
                        u_list = json.loads(uris)
                        for u in u_list:
                            u_clean = u.replace("file:///", "").replace("file://", "").replace("\\", "/").rstrip("/").lower()
                            folder_name = os.path.basename(u_clean)
                            if folder_name and folder_name in snip_norm:
                                score += 35 + len(folder_name) * 2
                            if target_cwd and folder_name == os.path.basename(target_cwd).lower():
                                score += 15
                    except Exception:
                        pass

                # Check transcript text match
                log_path = os.path.expanduser(f"~/.gemini/{app_dir}/brain/{cid}/.system_generated/logs/transcript.jsonl")
                if os.path.isfile(log_path):
                    try:
                        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                            tail_norm = clean_txt(f.read()[-8000:])
                            for ch in chunks[:25]:
                                if ch in tail_norm:
                                    score += 20
                    except Exception:
                        pass

                if score > best_score and score >= 20:
                    best_score = score
                    best_cid = cid
                    best_dir = app_dir
                    best_title = title
        except Exception:
            pass

    if best_cid:
        return best_cid, best_dir, best_title

    # Fallback to directory match
    clean_target = os.path.normpath(target_cwd).lower().replace("\\", "/") if target_cwd else ""
    for db_path in db_paths:
        if not os.path.isfile(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT conversation_id, workspace_uris, app_data_dir, title FROM conversation_summaries ORDER BY last_modified_time DESC LIMIT 20")
            rows = c.fetchall()
            conn.close()
            if clean_target:
                for cid, uris, app_dir, title in rows:
                    if uris and clean_target in uris.lower():
                        return cid, app_dir, title
            if rows:
                return rows[0][0], rows[0][2], rows[0][3]
        except Exception:
            pass

    return None, "antigravity-cli", None

def parse_antigravity_transcript(cid, app_data_dir, target_cwd=None, conv_title=None, live_quotas=None):
    now = time.time()
    gemini_5h_pct = 95.0
    gemini_week_pct = 55.0
    reset_5h_mins = 240

    if live_quotas and "gemini-5h" in live_quotas:
        g5h = live_quotas["gemini-5h"]
        gemini_5h_pct = g5h.get("percent_remaining", 95.0)
        reset_str = g5h.get("reset_time")
        if reset_str:
            t = parse_iso(reset_str)
            if t:
                reset_5h_mins = max(0, int((t - now) / 60))

    if live_quotas and "gemini-weekly" in live_quotas:
        gemini_week_pct = live_quotas["gemini-weekly"].get("percent_remaining", 55.0)

    session_in, session_out, session_cache = 0, 0, 0
    last_context = 0
    model_name = "Gemini 3.8 Flash"
    context_limit = 1_000_000

    if cid:
        log_paths = [
            os.path.expanduser(f"~/.gemini/{app_data_dir}/brain/{cid}/.system_generated/logs/transcript.jsonl"),
            os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{cid}/.system_generated/logs/transcript.jsonl"),
            os.path.expanduser(f"~/.gemini/antigravity/brain/{cid}/.system_generated/logs/transcript.jsonl")
        ]
        log_file = next((p for p in log_paths if os.path.isfile(p)), None)

        if log_file:
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        try:
                            item = json.loads(line)
                            in_tok = item.get("input_tokens") or 0
                            out_tok = item.get("output_tokens") or 0
                            cache_tok = item.get("cache_read_tokens") or item.get("cachedContentTokenCount") or 0

                            usage = item.get("usage") or item.get("token_usage")
                            if not usage and "response" in item:
                                usage = item["response"].get("usageMetadata")
                            if usage:
                                in_tok = usage.get("promptTokenCount", in_tok) or usage.get("input_tokens", in_tok)
                                out_tok = usage.get("candidatesTokenCount", out_tok) or usage.get("output_tokens", out_tok)
                                cache_tok = usage.get("cachedContentTokenCount", cache_tok) or usage.get("cache_read_input_tokens", cache_tok)

                            if in_tok or out_tok or cache_tok:
                                session_in += in_tok
                                session_out += out_tok
                                session_cache += cache_tok
                                last_context = in_tok + cache_tok
                            if "model" in item:
                                m = str(item["model"]).lower()
                                if "pro" in m:
                                    model_name = "Gemini 3.8 Pro"
                                    context_limit = 2_000_000
                                elif "flash" in m:
                                    model_name = "Gemini 3.8 Flash"
                                    context_limit = 1_000_000
                        except Exception:
                            pass
            except Exception:
                pass

    session_total = session_in + session_out + session_cache
    context_pct = (last_context / context_limit) * 100 if context_limit > 0 else 0
    project_name = os.path.basename(target_cwd) if target_cwd else "Codigo"

    return {
        "agent": "Antigravity",
        "connected": True,
        "model": model_name,
        "project": project_name,
        "workspace_cwd": target_cwd or "",
        "conversation_id": cid or "",
        "session_id": cid or "",
        "session_title": conv_title or "",
        "cache_key": f"{target_cwd}::antigravity::{cid}".lower() if cid else f"{target_cwd}::antigravity".lower(),
        "session": {
            "input_tokens": session_in,
            "output_tokens": session_out,
            "cache_tokens": session_cache,
            "total_tokens": session_total,
            "total_formatted": format_tokens(session_total)
        },
        "context": {
            "used": last_context,
            "limit": context_limit,
            "used_formatted": format_tokens(last_context),
            "limit_formatted": format_tokens(context_limit),
            "percent": round(context_pct, 1)
        },
        "quota_5h": {
            "percent_left": gemini_5h_pct,
            "reset_mins": reset_5h_mins
        },
        "quota_weekly": {
            "percent_left": gemini_week_pct
        },
        "updated_at": int(now)
    }

# ==============================================================================
# ADAPTER 1: ANTIGRAVITY (GEMINI)
# ==============================================================================
class AntigravityAdapter:
    def can_handle(self, agent_name, target_cwd):
        if agent_name:
            low = agent_name.lower()
            if "antigravity" in low or "gemini" in low:
                return True
            if "codex" in low or "claude" in low or "gpt" in low or "opencode" in low:
                return False
        return os.path.isdir(os.path.expanduser("~/.gemini/antigravity-cli/brain"))

    def collect(self, target_cwd, session_hint=None, screen_snippet=None):
        live_quotas = get_live_antigravity_quotas()
        cid, app_data_dir, title = find_conversation(target_cwd, session_hint, screen_snippet)
        return parse_antigravity_transcript(cid, app_data_dir, target_cwd, title, live_quotas)

    def collect_all_conversations(self, target_cwd=None, live_quotas=None):
        results = {}
        db_paths = [
            os.path.expanduser("~/.gemini/antigravity-cli/conversation_summaries.db"),
            os.path.expanduser("~/.gemini/antigravity/conversation_summaries.db")
        ]
        for db_path in db_paths:
            if not os.path.isfile(db_path):
                continue
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT conversation_id, workspace_uris, app_data_dir, title
                    FROM conversation_summaries
                    ORDER BY last_modified_time DESC LIMIT 20
                """)
                rows = cursor.fetchall()
                conn.close()
                for cid, uris, app_dir, title in rows:
                    entry = parse_antigravity_transcript(cid, app_dir, target_cwd, title, live_quotas)
                    if cid:
                        results[f"antigravity::{cid}".lower()] = entry
                        if target_cwd:
                            results[f"{target_cwd}::antigravity::{cid}".lower()] = entry
                    if title:
                        t_clean = title.strip().lower()
                        results[f"antigravity::{t_clean}"] = entry
                        if target_cwd:
                            results[f"{target_cwd}::antigravity::{t_clean}"] = entry
            except Exception:
                pass
        return results

# ==============================================================================
# ADAPTER 2: OPENAI CODEX
# ==============================================================================
class CodexAdapter:
    def can_handle(self, agent_name, target_cwd):
        if agent_name:
            low = agent_name.lower()
            return "codex" in low or "openai" in low or "gpt" in low
        return False

    def parse_rollout_file(self, matched_file, target_cwd=None, thread_name=None, thread_id=None):
        now = time.time()
        model_name = "GPT-6-Luna medium"
        total_in, total_out, total_tok = 0, 0, 0
        ctx_limit = 258400
        ctx_used = 0
        quota_pct = 100.0
        reset_mins = 0
        tid = thread_id or ""

        try:
            with open(matched_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        t = d.get("type")
                        p = d.get("payload", {})
                        if t == "world_state":
                            state = p.get("state", {})
                            cm = state.get("collaboration_mode", {})
                            if "model" in cm:
                                raw_m = cm["model"]
                                if "luna" in raw_m.lower():
                                    model_name = "GPT-6-Luna medium"
                                elif "codex" in raw_m.lower():
                                    model_name = "OpenAI Codex"
                                else:
                                    model_name = raw_m.title()
                        elif t == "token_usage_record":
                            if "thread_id" in p:
                                tid = p["thread_id"]
                            u = p.get("thread_token_usage") or p.get("usage", {})
                            total_in = u.get("input_tokens", total_in)
                            total_out = u.get("output_tokens", total_out)
                            total_tok = u.get("total_tokens", total_tok)
                        elif t == "event_msg":
                            if p.get("type") == "token_count":
                                info = p.get("info", {})
                                ctx_limit = info.get("model_context_window", ctx_limit)
                                last_u = info.get("last_token_usage", {})
                                ctx_used = last_u.get("total_tokens", ctx_used)
                                rl = p.get("rate_limits", {}).get("primary")
                                if rl and "used_percent" in rl:
                                    quota_pct = max(0.0, 100.0 - float(rl["used_percent"]))
                                    if "resets_at" in rl and rl["resets_at"]:
                                        reset_mins = max(0, int((rl["resets_at"] - now) / 60))
                    except Exception:
                        pass
        except Exception:
            pass

        project_name = os.path.basename(target_cwd) if target_cwd else "Codigo"
        context_pct = round((ctx_used / ctx_limit) * 100, 1) if ctx_limit > 0 else 0.0

        return {
            "agent": "Codex",
            "connected": True,
            "model": model_name,
            "project": project_name,
            "workspace_cwd": target_cwd or "",
            "session_id": tid,
            "session_title": thread_name or "",
            "cache_key": f"{target_cwd}::codex::{tid}".lower() if tid else f"{target_cwd}::codex".lower(),
            "session": {
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_tok,
                "total_formatted": format_tokens(total_tok)
            },
            "context": {
                "used": ctx_used,
                "limit": ctx_limit,
                "used_formatted": format_tokens(ctx_used),
                "limit_formatted": format_tokens(ctx_limit),
                "percent": context_pct
            },
            "quota_5h": {
                "percent_left": round(quota_pct, 1),
                "reset_mins": reset_mins
            },
            "quota_weekly": {
                "percent_left": round(quota_pct, 1)
            },
            "updated_at": int(now)
        }

    def find_codex_dir(self):
        candidates = []
        if os.environ.get("CODEX_HOME"):
            candidates.append(os.environ["CODEX_HOME"])
        candidates.extend([
            os.path.expanduser("~/.codex"),
            os.path.expanduser("~/Library/Application Support/codex"),
            os.path.expanduser("~/.config/codex")
        ])
        if sys.platform == "win32" and os.environ.get("USERPROFILE"):
            candidates.append(os.path.join(os.environ["USERPROFILE"], ".codex"))
        for d in candidates:
            if d and os.path.isdir(d):
                return os.path.normpath(d)
        return os.path.expanduser("~/.codex")

    def collect(self, target_cwd, session_hint=None, screen_snippet=None):
        now = time.time()
        codex_dir = self.find_codex_dir()
        idx_path = os.path.join(codex_dir, "session_index.jsonl")

        threads = []
        if os.path.isfile(idx_path):
            try:
                with open(idx_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.strip():
                            threads.append(json.loads(line))
            except Exception:
                pass

        matched_thread = None
        hint_low = (session_hint or "").strip().lower()
        snip_low = (screen_snippet or "").lower()

        # 1. Match by session_hint
        if hint_low:
            for t in threads:
                tname = (t.get("thread_name") or "").lower()
                tid = (t.get("id") or "").lower()
                if hint_low == tname or hint_low in tname or hint_low == tid:
                    matched_thread = t
                    break

        # 2. Match from screen_snippet
        if not matched_thread and snip_low:
            for t in threads:
                tname = (t.get("thread_name") or "").lower()
                if tname and tname in snip_low:
                    matched_thread = t
                    break

        # 3. If matched thread found, locate rollout file
        if matched_thread:
            tid = matched_thread.get("id")
            tname = matched_thread.get("thread_name")
            rollouts = glob.glob(os.path.join(codex_dir, "sessions", "**", f"*{tid}*.jsonl"), recursive=True)
            if rollouts:
                return self.parse_rollout_file(rollouts[0], target_cwd, tname, tid)

        # 4. If threads exist, fall back to the most recent thread instead of 0 tokens
        if threads:
            latest = threads[-1]
            tid = latest.get("id")
            tname = latest.get("thread_name")
            rollouts = glob.glob(os.path.join(codex_dir, "sessions", "**", f"*{tid}*.jsonl"), recursive=True)
            if rollouts:
                return self.parse_rollout_file(rollouts[0], target_cwd, tname, tid)

        # 5. If screen indicates Codex is running but it's a completely new session with no threads
        is_codex_active = snip_low and ("codex" in snip_low or "gpt" in snip_low or "ask codex" in snip_low)
        if is_codex_active or not threads:
            return {
                "agent": "Codex",
                "connected": True,
                "model": "GPT-6-Luna medium",
                "status_message": "nueva sesión / sin mensajes",
                "project": os.path.basename(target_cwd) if target_cwd else "Codigo",
                "workspace_cwd": target_cwd or "",
                "session_id": "new",
                "session_title": session_hint or "",
                "cache_key": f"{target_cwd}::codex::new".lower(),
                "session": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "total_formatted": "0"},
                "context": {"used": 0, "limit": 258400, "used_formatted": "0", "limit_formatted": "258.4k", "percent": 0.0},
                "quota_5h": {"percent_left": 100.0, "reset_mins": 0},
                "quota_weekly": {"percent_left": 100.0},
                "updated_at": int(now)
            }

        # 5. Fallback to latest rollout if nothing else specified
        all_rollouts = glob.glob(os.path.join(codex_dir, "sessions", "**", "rollout-*.jsonl"), recursive=True)
        if all_rollouts:
            all_rollouts.sort(key=os.path.getmtime, reverse=True)
            return self.parse_rollout_file(all_rollouts[0], target_cwd)

        return {
            "agent": "Codex",
            "connected": False,
            "model": "OpenAI Codex",
            "status_message": "sin sesión / no conectado",
            "project": os.path.basename(target_cwd) if target_cwd else "Workspace",
            "workspace_cwd": target_cwd or "",
            "session": {"total_formatted": "0"},
            "context": {"used_formatted": "0", "limit_formatted": "0", "percent": 0},
            "quota_5h": {"percent_left": 0, "reset_mins": 0},
            "quota_weekly": {"percent_left": 0},
            "updated_at": int(now)
        }

    def collect_all_threads(self, target_cwd=None):
        results = {}
        codex_dir = self.find_codex_dir()
        idx_path = os.path.join(codex_dir, "session_index.jsonl")
        if not os.path.isfile(idx_path):
            return results

        try:
            with open(idx_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                        tid = d.get("id")
                        tname = d.get("thread_name")
                        if not tid:
                            continue
                        rollouts = glob.glob(os.path.join(codex_dir, "sessions", "**", f"*{tid}*.jsonl"), recursive=True)
                        if rollouts:
                            entry = self.parse_rollout_file(rollouts[0], target_cwd, tname, tid)
                            results[f"codex::{tid}".lower()] = entry
                            if target_cwd:
                                results[f"{target_cwd}::codex::{tid}".lower()] = entry
                            if tname:
                                t_clean = tname.strip().lower()
                                results[f"codex::{t_clean}"] = entry
                                if target_cwd:
                                    results[f"{target_cwd}::codex::{t_clean}"] = entry
                    except Exception:
                        pass
        except Exception:
            pass
        return results

# ==============================================================================
# ADAPTER 3: CLAUDE CODE
# ==============================================================================
class ClaudeCodeAdapter:
    def can_handle(self, agent_name, target_cwd):
        if agent_name:
            low = agent_name.lower()
            return "claude" in low or "anthropic" in low
        return False

    def find_claude_dir(self):
        candidates = []
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            candidates.append(os.environ["CLAUDE_CONFIG_DIR"])
        candidates.extend([
            os.path.expanduser("~/.claude"),
            os.path.expanduser("~/Library/Application Support/claude"),
            os.path.expanduser("~/.config/claude")
        ])
        for d in candidates:
            if d and os.path.isdir(d):
                return os.path.normpath(d)
        return os.path.expanduser("~/.claude")

    def collect(self, target_cwd, session_hint=None, screen_snippet=None):
        now = time.time()
        claude_dir = self.find_claude_dir()
        claude_auth = os.path.isfile(os.path.expanduser("~/.claude.json")) or os.path.isdir(claude_dir)
        session_files = glob.glob(os.path.join(claude_dir, "sessions", "**", "*.json*"), recursive=True)
        if not session_files and not claude_auth:
            return {
                "agent": "Claude Code",
                "connected": False,
                "model": "Claude",
                "status_message": "sin sesión / no conectado",
                "project": os.path.basename(target_cwd) if target_cwd else "Workspace",
                "workspace_cwd": target_cwd or "",
                "cache_key": f"{target_cwd}::claude".lower(),
                "session": {"total_formatted": "0"},
                "context": {"used_formatted": "0", "limit_formatted": "0", "percent": 0},
                "quota_5h": {"percent_left": 0, "reset_mins": 0},
                "quota_weekly": {"percent_left": 0},
                "updated_at": int(now)
            }

        model_name = "Claude 3.7 Sonnet"
        total_tokens = 0
        context_used = 0
        context_limit = 200000

        if session_files:
            session_files.sort(key=os.path.getmtime, reverse=True)
            matched = session_files[0]
            if session_hint:
                for sf in session_files:
                    if session_hint.lower() in sf.lower():
                        matched = sf
                        break
            try:
                with open(matched, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    total_tokens = data.get("total_tokens", total_tokens)
                    context_used = data.get("context_tokens", context_used)
                    if "model" in data:
                        model_name = data["model"]
            except Exception:
                pass

        project_name = os.path.basename(target_cwd) if target_cwd else "Workspace"
        context_pct = round((context_used / context_limit) * 100, 1) if context_limit > 0 else 0.0

        return {
            "agent": "Claude Code",
            "connected": True,
            "model": model_name,
            "project": project_name,
            "workspace_cwd": target_cwd or "",
            "cache_key": f"{target_cwd}::claude".lower(),
            "session": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": total_tokens,
                "total_formatted": format_tokens(total_tokens)
            },
            "context": {
                "used": context_used,
                "limit": context_limit,
                "used_formatted": format_tokens(context_used),
                "limit_formatted": format_tokens(context_limit),
                "percent": context_pct
            },
            "quota_5h": {
                "percent_left": 85.0,
                "reset_mins": 45
            },
            "quota_weekly": {
                "percent_left": 75.0
            },
            "updated_at": int(now)
        }

# ==============================================================================
# ADAPTER 4: OPENCODE
# ==============================================================================
class OpenCodeAdapter:
    def can_handle(self, agent_name, target_cwd):
        if agent_name:
            low = agent_name.lower()
            return "opencode" in low
        return False

    def find_opencode_db(self):
        env_custom = os.environ.get("OPENCODE_DATA_DIR")
        candidates = []
        if env_custom:
            candidates.append(os.path.join(env_custom, "opencode.db") if not env_custom.endswith(".db") else env_custom)
        if os.environ.get("XDG_DATA_HOME"):
            candidates.append(os.path.join(os.environ["XDG_DATA_HOME"], "opencode", "opencode.db"))

        candidates.extend([
            os.path.expanduser("~/.local/share/opencode/opencode.db"),
            os.path.expandvars("%LOCALAPPDATA%/opencode/opencode.db"),
            os.path.expandvars("%APPDATA%/opencode/opencode.db"),
            os.path.expanduser("~/.config/opencode/opencode.db"),
            os.path.expanduser("~/.opencode/opencode.db")
        ])

        for c in candidates:
            if c:
                norm = os.path.normpath(c)
                if os.path.isfile(norm):
                    return norm
        return None

    def parse_session_row(self, row, target_cwd=None):
        now = time.time()
        sid, title, raw_model, t_in, t_out, t_cache, directory, time_updated = row
        t_in = t_in or 0
        t_out = t_out or 0
        t_cache = t_cache or 0
        total_tokens = t_in + t_out + t_cache
        last_context = t_in + t_cache

        model_name = "DeepSeek V4.1 Flash"
        context_limit = 128000
        if raw_model:
            try:
                m_obj = json.loads(raw_model) if isinstance(raw_model, str) and raw_model.startswith("{") else {"id": str(raw_model)}
                mid = m_obj.get("id", "")
                if "deepseek" in mid.lower():
                    model_name = "DeepSeek V4.1 Flash"
                    context_limit = 128000
                elif "claude" in mid.lower():
                    model_name = "Claude 3.7 Sonnet"
                    context_limit = 200000
                elif "gpt" in mid.lower():
                    model_name = "GPT-4o"
                    context_limit = 128000
                elif mid:
                    model_name = mid.replace("-", " ").title()
            except Exception:
                model_name = str(raw_model)

        project_name = os.path.basename(directory) if directory else (os.path.basename(target_cwd) if target_cwd else "Workspace")
        context_pct = round((last_context / context_limit) * 100, 1) if context_limit > 0 else 0.0

        return {
            "agent": "OpenCode",
            "connected": True,
            "model": model_name,
            "project": project_name,
            "session_id": sid or "",
            "session_title": title or "",
            "workspace_cwd": directory or target_cwd or "",
            "cache_key": f"{target_cwd}::opencode::{sid}".lower() if sid else f"{target_cwd}::opencode".lower(),
            "session": {
                "input_tokens": t_in,
                "output_tokens": t_out,
                "cache_tokens": t_cache,
                "total_tokens": total_tokens,
                "total_formatted": format_tokens(total_tokens)
            },
            "context": {
                "used": last_context,
                "limit": context_limit,
                "used_formatted": format_tokens(last_context),
                "limit_formatted": format_tokens(context_limit),
                "percent": context_pct
            },
            "quota_5h": {
                "percent_left": 100.0,
                "reset_mins": 0
            },
            "quota_weekly": {
                "percent_left": 100.0
            },
            "updated_at": int(now)
        }

    def collect(self, target_cwd, session_hint=None, screen_snippet=None):
        now = time.time()
        db_path = self.find_opencode_db()

        if db_path:
            try:
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                clean_target = os.path.normpath(target_cwd).lower().replace("\\", "/") if target_cwd else ""
                snip_low = (screen_snippet or "").lower()
                hint_low = (session_hint or "").strip().lower()
                row = None

                # 1. Match specific session hint if provided
                if hint_low:
                    c.execute("""
                        SELECT s.id, s.title, s.model, s.tokens_input, s.tokens_output, s.tokens_cache_read, s.directory, s.time_updated
                        FROM session_v2 s
                        WHERE s.id = ? OR LOWER(s.title) = ? OR LOWER(s.title) LIKE ?
                        ORDER BY s.time_updated DESC LIMIT 1
                    """, (session_hint, hint_low, f"%{hint_low}%"))
                    row = c.fetchone()

                # 2. Match from screen snippet
                if not row and snip_low:
                    c.execute("""
                        SELECT s.id, s.title, s.model, s.tokens_input, s.tokens_output, s.tokens_cache_read, s.directory, s.time_updated
                        FROM session_v2 s
                        ORDER BY s.time_updated DESC LIMIT 40
                    """)
                    for r in c.fetchall():
                        stitle = (r[1] or "").lower()
                        sid = (r[0] or "").lower()
                        if (stitle and stitle in snip_low) or (sid and sid in snip_low):
                            row = r
                            break

                conn.close()

                if row:
                    return self.parse_session_row(row, target_cwd)

                # 3. If screen indicates OpenCode is running, it's a new or empty session
                is_opencode_active = snip_low and ("opencode" in snip_low or "deepseek" in snip_low or "ctrl+p" in snip_low)
                if is_opencode_active or hint_low:
                    return {
                        "agent": "OpenCode",
                        "connected": True,
                        "model": "DeepSeek V4.1 Flash",
                        "status_message": "nueva sesión / sin mensajes",
                        "project": os.path.basename(target_cwd) if target_cwd else "Codigo",
                        "workspace_cwd": target_cwd or "",
                        "session_id": "new",
                        "session_title": session_hint or "",
                        "cache_key": f"{target_cwd}::opencode::new".lower(),
                        "session": {"input_tokens": 0, "output_tokens": 0, "cache_tokens": 0, "total_tokens": 0, "total_formatted": "0"},
                        "context": {"used": 0, "limit": 128000, "used_formatted": "0", "limit_formatted": "128.0k", "percent": 0.0},
                        "quota_5h": {"percent_left": 100.0, "reset_mins": 0},
                        "quota_weekly": {"percent_left": 100.0},
                        "updated_at": int(now)
                    }
            except Exception:
                pass

        return {
            "agent": "OpenCode",
            "connected": False,
            "model": "OpenCode",
            "status_message": "sin sesión / no conectado",
            "project": os.path.basename(target_cwd) if target_cwd else "Workspace",
            "workspace_cwd": target_cwd or "",
            "session": {"total_formatted": "0"},
            "context": {"used_formatted": "0", "limit_formatted": "0", "percent": 0},
            "quota_5h": {"percent_left": 100, "reset_mins": 0},
            "quota_weekly": {"percent_left": 100},
            "updated_at": int(now)
        }

    def collect_all_sessions(self, target_cwd=None):
        results = {}
        db_path = self.find_opencode_db()
        if not db_path or not os.path.isfile(db_path):
            return results

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                SELECT s.id, s.title, s.model, s.tokens_input, s.tokens_output, s.tokens_cache_read, s.directory, s.time_updated
                FROM session_v2 s
                ORDER BY s.time_updated DESC LIMIT 40
            """)
            for row in c.fetchall():
                entry = self.parse_session_row(row, target_cwd)
                sid = entry.get("session_id")
                stitle = entry.get("session_title")
                sdir = entry.get("workspace_cwd") or target_cwd
                if sid:
                    results[f"opencode::{sid}".lower()] = entry
                    if sdir:
                        results[f"{sdir}::opencode::{sid}".lower()] = entry
                if stitle:
                    t_clean = stitle.strip().lower()
                    results[f"opencode::{t_clean}"] = entry
                    if sdir:
                        results[f"{sdir}::opencode::{t_clean}"] = entry
            conn.close()
        except Exception:
            pass
        return results

# ==============================================================================
# DISPATCH & AGGREGATION
# ==============================================================================
def collect_any(target_cwd=None, agent_hint=None, session_hint=None, screen_snippet=None):
    if agent_hint:
        low = agent_hint.lower()
        if "codex" in low or "openai" in low or "gpt" in low:
            return CodexAdapter().collect(target_cwd, session_hint, screen_snippet)
        if "opencode" in low or "deepseek" in low:
            return OpenCodeAdapter().collect(target_cwd, session_hint, screen_snippet)
        if "claude" in low or "anthropic" in low:
            return ClaudeCodeAdapter().collect(target_cwd, session_hint, screen_snippet)
        if "antigravity" in low or "gemini" in low:
            return AntigravityAdapter().collect(target_cwd, session_hint, screen_snippet)

    adapters = [CodexAdapter(), OpenCodeAdapter(), ClaudeCodeAdapter(), AntigravityAdapter()]
    for ad in adapters:
        if ad.can_handle(agent_hint, target_cwd):
            try:
                res = ad.collect(target_cwd, session_hint, screen_snippet)
                if res and res.get("connected"):
                    return res
            except Exception:
                pass

    return AntigravityAdapter().collect(target_cwd, session_hint, screen_snippet)

def collect_all(target_cwd=None, term_id=None, active_data=None):
    results = {}
    live_quotas = get_live_antigravity_quotas()

    # 1. Index all recent sessions across providers
    try:
        results.update(CodexAdapter().collect_all_threads(target_cwd))
    except Exception:
        pass

    try:
        results.update(OpenCodeAdapter().collect_all_sessions(target_cwd))
    except Exception:
        pass

    try:
        results.update(AntigravityAdapter().collect_all_conversations(target_cwd, live_quotas))
    except Exception:
        pass

    # 2. Bind active terminal explicitly to prevent cross-session bleeding
    if term_id and active_data:
        t_key = f"term::{term_id}".lower()
        results[t_key] = active_data
        if target_cwd:
            results[f"{target_cwd}::{t_key}"] = active_data

    return results

def main():
    try:
        dbg_log = os.path.expanduser("~/.config/herdr-app/data/collector_debug.log")
        with open(dbg_log, "a", encoding="utf-8") as f_dbg:
            f_dbg.write(f"[{datetime.now().isoformat()}] argv: {sys.argv}\n")
    except Exception:
        pass

    target_cwd = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] and sys.argv[1] not in ("-", "none") else None
    agent_hint = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] and sys.argv[2] not in ("-", "none") else None
    session_hint = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] and sys.argv[3] not in ("-", "none") else None
    term_id = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] and sys.argv[4] not in ("-", "none") else None
    screen_snippet = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] and sys.argv[5] not in ("-", "none") else None

    active_data = collect_any(target_cwd, agent_hint, session_hint, screen_snippet)
    all_data = collect_all(target_cwd, term_id, active_data)

    combined = {
        "active": active_data,
        "by_key": all_data,
        "updated_at": int(time.time())
    }

    if active_data:
        for k, v in active_data.items():
            combined[k] = v

    print(json.dumps(combined, indent=2))

    try:
        out_path = os.path.expanduser("~/.config/herdr-app/data/agent_quota.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2)
    except Exception:
        pass

if __name__ == "__main__":
    main()
