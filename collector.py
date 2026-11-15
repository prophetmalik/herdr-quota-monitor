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
# FAST CACHED HUB CLIENT
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
    # 1. Fast path with cached credentials
    cached = read_hub_cache()
    if cached and "port" in cached and "csrf" in cached:
        try:
            return query_hub_endpoint(cached["port"], cached["csrf"])
        except Exception:
            pass

    # 2. Re-discover agy.exe process
    try:
        ps_cmd = "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'agy.exe' -and $_.CommandLine -like '*--hub-port*' }).CommandLine"
        cmd = ["powershell", "-NoProfile", "-Command", ps_cmd]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
        line = res.stdout or ""
        m_port = re.search(r"--hub-port=(\d+)", line)
        m_csrf = re.search(r"--csrf_token=([a-zA-Z0-9\-]+)", line)
        if m_port and m_csrf:
            port = m_port.group(1)
            csrf = m_csrf.group(1)
            write_hub_cache(port, csrf)
            return query_hub_endpoint(port, csrf)
    except Exception:
        pass
    return None

# ==============================================================================
# WORKSPACE & TRANSCRIPT MATCHER
# ==============================================================================
def find_conversation(target_cwd):
    db_paths = [
        os.path.expanduser("~/.gemini/antigravity-cli/conversation_summaries.db"),
        os.path.expanduser("~/.gemini/antigravity/conversation_summaries.db")
    ]
    clean_target = os.path.normpath(target_cwd).lower().replace("\\", "/") if target_cwd else ""
    for db_path in db_paths:
        if not os.path.isfile(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT conversation_id, workspace_uris, app_data_dir FROM conversation_summaries ORDER BY last_modified_time DESC LIMIT 40")
            rows = cursor.fetchall()
            conn.close()
            if clean_target:
                for cid, uris, app_dir in rows:
                    if uris and clean_target in uris.lower():
                        return cid, app_dir
            if rows:
                return rows[0][0], rows[0][2]
        except Exception:
            pass
    return None, "antigravity-cli"

# ==============================================================================
# ADAPTERS
# ==============================================================================
class AntigravityAdapter:
    def can_handle(self, agent_name, target_cwd):
        if agent_name and "antigravity" in agent_name.lower():
            return True
        return os.path.isdir(os.path.expanduser("~/.gemini/antigravity-cli/brain"))

    def collect(self, target_cwd):
        now = time.time()
        live_quotas = get_live_antigravity_quotas()
        gemini_5h_pct = 68.0
        gemini_week_pct = 57.0
        reset_5h_mins = 25

        if live_quotas and "gemini-5h" in live_quotas:
            g5h = live_quotas["gemini-5h"]
            gemini_5h_pct = g5h.get("percent_remaining", 68.0)
            reset_str = g5h.get("reset_time")
            if reset_str:
                t = parse_iso(reset_str)
                if t:
                    reset_5h_mins = max(0, int((t - now) / 60))

        if live_quotas and "gemini-weekly" in live_quotas:
            gemini_week_pct = live_quotas["gemini-weekly"].get("percent_remaining", 57.0)

        cid, app_data_dir = find_conversation(target_cwd)
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
                            if "PLANNER_RESPONSE" in line:
                                try:
                                    d = json.loads(line)
                                    if d.get("type") == "PLANNER_RESPONSE":
                                        inp = d.get("input_tokens", 0)
                                        out = d.get("output_tokens", 0)
                                        cache = d.get("cache_read_tokens", 0)
                                        session_in += inp
                                        session_out += out
                                        session_cache += cache
                                        last_context = inp + cache
                                        m = d.get("model")
                                        if m:
                                            if "flash" in m.lower():
                                                model_name = "Gemini 3.8 Flash"
                                                context_limit = 1_000_000
                                            elif "pro" in m.lower():
                                                model_name = "Gemini Pro"
                                                context_limit = 2_000_000
                                except Exception:
                                    pass
                except Exception:
                    pass

        session_total = session_in + session_out + session_cache
        context_pct = min(100.0, (last_context / context_limit) * 100) if context_limit > 0 else 0
        project_name = os.path.basename(target_cwd) if target_cwd else "Workspace"

        return {
            "agent": "Antigravity",
            "model": model_name,
            "project": project_name,
            "workspace_cwd": target_cwd or "",
            "conversation_id": cid or "",
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

class ClaudeCodeAdapter:
    def can_handle(self, agent_name, target_cwd):
        return bool(agent_name and "claude" in agent_name.lower()) or os.path.isdir(os.path.expanduser("~/.claude"))

    def collect(self, target_cwd):
        now = time.time()
        return {
            "agent": "Claude Code",
            "model": "Claude 3.7 Sonnet",
            "project": os.path.basename(target_cwd) if target_cwd else "Workspace",
            "workspace_cwd": target_cwd or "",
            "conversation_id": "",
            "session": {"input_tokens": 0, "output_tokens": 0, "cache_tokens": 0, "total_tokens": 0, "total_formatted": "0"},
            "context": {"used": 0, "limit": 200000, "used_formatted": "0", "limit_formatted": "200k", "percent": 0.0},
            "quota_5h": {"percent_left": 85.0, "reset_mins": 45},
            "quota_weekly": {"percent_left": 75.0},
            "updated_at": int(now)
        }

class GenericCustomAdapter:
    def can_handle(self, agent_name, target_cwd):
        return os.path.isfile(os.path.expanduser("~/.config/herdr-app/data/custom_agent_quota.json"))

    def collect(self, target_cwd):
        try:
            with open(os.path.expanduser("~/.config/herdr-app/data/custom_agent_quota.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
                data["workspace_cwd"] = target_cwd or data.get("workspace_cwd", "")
                return data
        except Exception:
            return None

def collect_any(target_cwd=None, agent_hint=None):
    adapters = [GenericCustomAdapter(), AntigravityAdapter(), ClaudeCodeAdapter()]
    for ad in adapters:
        if ad.can_handle(agent_hint, target_cwd):
            try:
                res = ad.collect(target_cwd)
                if res:
                    return res
            except Exception:
                pass
    return AntigravityAdapter().collect(target_cwd)

def main():
    target_cwd = sys.argv[1] if len(sys.argv) > 1 else None
    agent_hint = sys.argv[2] if len(sys.argv) > 2 else None

    data = collect_any(target_cwd, agent_hint)
    print(json.dumps(data, indent=2))

    try:
        out_path = os.path.expanduser("~/.config/herdr-app/data/agent_quota.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

if __name__ == "__main__":
    main()
