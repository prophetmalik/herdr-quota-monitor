import { View, div, svg } from "gpui-kit";
import { h_flex } from "gpui-base";
import {
  spaces,
  agents,
  panes,
  terminals,
  focused,
  theme,
  run,
  window,
  keys,
  readTextFile,
  watchFolder,
  appHome,
  exec,
  hc
} from "herdr";

export default class WorkspaceStatus extends View {
  init(_props, cx) {
    this.cache = {};
    this.termMetrics = {};
    this.pinnedAgent = {};
    this.pinnedSession = {};
    this.lastScreen = {};

    this.refresh(cx);

    const dataDir = `${appHome()}/data`.replace(/\\/g, "/");
    cx.spawn(async (cx) => {
      try {
        for (;;) {
          await watchFolder(dataDir);
          await this.load(cx);
        }
      } catch (_e) {}
    });

    cx.timer.every(2000, (cx) => this.refresh(cx));
  }

  getFocusedInfo() {
    const f = typeof focused === "function" ? focused() : null;
    const spaceList = typeof spaces === "function" ? spaces() : [];
    const space = spaceList.find((s) => s.active);
    const allPanes = typeof panes === "function" ? panes() : [];
    const allAgents = typeof agents === "function" ? agents() : [];
    const activeTab = space?.tabs?.find((t) => t.active);

    let termId = f?.terminal || "";
    let pane = null;
    if (termId) {
      pane = allPanes.find((p) => p.terminal === termId);
    }
    if (!pane && f?.pane) {
      pane = allPanes.find((p) => p.pane === f.pane);
      if (pane?.terminal) termId = pane.terminal;
    }
    if (!pane && activeTab) {
      pane =
        allPanes.find((p) => p.tab === activeTab.id && p.focused) ||
        allPanes.find((p) => p.tab === activeTab.id);
      if (pane?.terminal) termId = pane.terminal;
    }
    if (!pane) {
      pane = allPanes.find((p) => p.focused);
      if (pane?.terminal) termId = pane.terminal;
    }

    let activeAgent = null;
    if (f?.agent) {
      activeAgent = allAgents.find((a) => a.id === f.agent);
    }
    if (!activeAgent && termId) {
      activeAgent = allAgents.find((a) => a.terminal === termId);
    }
    if (!activeAgent && pane?.tab) {
      activeAgent = allAgents.find((a) => a.tab === pane.tab);
    }
    if (!activeAgent && activeTab?.id) {
      activeAgent = allAgents.find((a) => a.tab === activeTab.id);
    }

    const cwd = pane?.cwd || f?.cwd || space?.folder || "";
    const tabId = activeTab?.id || pane?.tab || f?.tab || "";
    const title = pane?.title || activeAgent?.title || f?.title || "";
    const prog =
      pane?.program?.name ||
      pane?.program?.key ||
      activeAgent?.app ||
      activeAgent?.name ||
      "";

    return { termId, tabId, cwd, title, prog, pane, activeAgent, space };
  }

  detectAgent(info, screenSnippet = "") {
    if (info.activeAgent) {
      const k = `${info.activeAgent.key || ""} ${info.activeAgent.app || ""} ${info.activeAgent.name || ""}`.toLowerCase();
      if (k.includes("antigravity") || k.includes("gemini") || k.includes("agy")) return "antigravity";
      if (k.includes("codex") || k.includes("openai")) return "codex";
      if (k.includes("opencode")) return "opencode";
      if (k.includes("claude") || k.includes("anthropic")) return "claude";
    }

    const progName = (info.pane?.program?.name || info.pane?.program?.key || info.prog || "").toLowerCase();
    if (progName.includes("antigravity") || progName.includes("gemini") || progName.includes("agy")) return "antigravity";
    if (progName.includes("codex") || progName.includes("openai")) return "codex";
    if (progName.includes("opencode")) return "opencode";
    if (progName.includes("claude") || progName.includes("anthropic")) return "claude";

    const combined = `${info.prog} ${info.title} ${screenSnippet}`.toLowerCase();
    if (
      combined.includes("codex") ||
      combined.includes("openai") ||
      combined.includes("gpt-6") ||
      combined.includes("gpt-5") ||
      combined.includes("gpt-4")
    ) {
      return "codex";
    }
    if (combined.includes("opencode") || combined.includes("deepseek")) {
      return "opencode";
    }
    if (combined.includes("claude") || combined.includes("anthropic")) {
      return "claude";
    }
    if (combined.includes("antigravity") || combined.includes("gemini") || combined.includes("google")) {
      return "antigravity";
    }
    return "";
  }

  async load(cx) {
    try {
      const p = `${appHome()}/data/agent_quota.json`.replace(/\\/g, "/");
      const txt = await readTextFile(p);
      if (!txt) return;
      const data = JSON.parse(txt);

      if (data.by_key) {
        Object.assign(this.cache, data.by_key);
      }

      const info = this.getFocusedInfo();
      const termId = info.termId;
      if (termId) {
        const termKey = `term::${termId}`.toLowerCase();
        const incoming = this.cache[termKey];
        if (incoming) {
          const current = this.termMetrics[termId];
          const curTok = current?.session?.total_tokens || 0;
          const incTok = incoming?.session?.total_tokens || 0;
          // Sticky metrics: keep valid data instead of flickering to 0 while generating
          if (incTok > 0 || curTok === 0 || !current?.connected) {
            this.termMetrics[termId] = incoming;
            if (incoming.session_id && incoming.session_id !== "new") {
              this.pinnedSession[termId] = incoming.session_id;
            } else if (incoming.session_title) {
              this.pinnedSession[termId] = incoming.session_title;
            }
          }
        }
      }

      cx.notify();
    } catch (_e) {}
  }

  async refresh(cx) {
    const info = this.getFocusedInfo();
    const { termId, cwd, title } = info;

    let screenSnippet = "";
    if (termId && typeof hc === "function") {
      try {
        const res = await hc(["read", termId, "--lines", "25"]);
        screenSnippet = (res?.stdout || (typeof res === "string" ? res : "") || "").trim();
      } catch (_e) {}
    }

    let agentName = this.detectAgent(info, screenSnippet);
    if (agentName && termId) {
      this.pinnedAgent[termId] = agentName;
    } else if (!agentName && termId && this.pinnedAgent[termId]) {
      // Retain active agent to avoid flicker during tool execution or scrolling
      agentName = this.pinnedAgent[termId];
    }

    // Filter out executable file paths or shell names
    let sessionHint = "";
    if (title && !/(\.exe|powershell|pwsh|cmd|bash|zsh|terminal|tb\d+)/i.test(title.trim())) {
      sessionHint = title.trim();
    }
    if (!sessionHint && termId && agentName === "codex" && this.pinnedSession[termId]) {
      sessionHint = this.pinnedSession[termId];
    }

    // Subfolder check based on active prompt in screen
    let effectiveCwd = cwd;
    if (screenSnippet.includes("herdr-quota-monitor") && !effectiveCwd.includes("herdr-quota-monitor")) {
      effectiveCwd = `${effectiveCwd}/herdr-quota-monitor`.replace(/\\/g, "/");
    }

    // Try finding matching cached session if not explicit
    if (!sessionHint && screenSnippet) {
      for (const k of Object.keys(this.cache)) {
        if (agentName && !k.startsWith(`${agentName}::`) && !k.includes(`::${agentName}::`)) continue;
        const item = this.cache[k];
        const sTitle = item?.session_title || item?.title;
        if (sTitle && screenSnippet.toLowerCase().includes(sTitle.toLowerCase())) {
          sessionHint = sTitle;
          break;
        }
      }
    }

    if (agentName) {
      try {
        const py = `${appHome()}/mods/agent-quota-bar/collector.py`.replace(/\\/g, "/");
        const cleanScreen = screenSnippet.replace(/[\r\n\t]+/g, " ").slice(0, 250);
        const sHint = sessionHint || "-";
        const tId = termId || "-";
        const args = [py, effectiveCwd || "", agentName, sHint, tId, cleanScreen];
        let ran = false;
        try {
          await exec("python", args);
          ran = true;
        } catch (_e) {}
        if (!ran) {
          try {
            await exec("python3", args);
            ran = true;
          } catch (_e2) {}
        }
        if (ran) {
          await this.load(cx);
        }
      } catch (_e) {}
    } else {
      if (termId && !this.pinnedAgent[termId]) {
        this.termMetrics[termId] = {
          agent: "Terminal",
          connected: false,
          status_message: "sin agente conectado",
          session: { total_formatted: "0" },
          context: { used_formatted: "0", limit_formatted: "0", percent: 0 },
          quota_5h: { percent_left: 100, reset_mins: 0 },
          quota_weekly: { percent_left: 100 }
        };
        cx.notify();
      }
    }
  }

  hint() {
    const mac = typeof window === "function" && window()?.platform === "macos";
    const mod = {
      cmd: mac ? "⌘" : "Ctrl+",
      ctrl: mac ? "⌃" : "Ctrl+",
      shift: mac ? "⇧" : "Shift+",
      alt: mac ? "⌥" : "Alt+",
      option: mac ? "⌥" : "Alt+"
    };
    const keyList = typeof keys === "function" ? keys() : [];
    const b = keyList.find((k) => k.section === "global" && k.action === "app.palette");
    const parts = b && b.keys.endsWith("--") ? [...b.keys.slice(0, -2).split("-"), "-"] : b?.keys.split("-");
    const key = parts && parts.map((p) => mod[p.toLowerCase()] ?? p.toUpperCase()).join("");
    return key ? `${key}  commands` : "commands";
  }

  render() {
    const t = typeof theme === "function" ? theme() : {};
    const info = this.getFocusedInfo();
    const termId = info.termId;

    // 1. Terminal-specific isolated metrics
    let m = termId ? this.termMetrics[termId] || this.cache[`term::${termId}`.toLowerCase()] : null;

    // 2. Direct title match if not found by terminal ID
    if (!m && info.title) {
      const cleanTitle = info.title.toLowerCase();
      m = this.cache[`${info.cwd}::${cleanTitle}`] || this.cache[cleanTitle];
    }

    // 3. Fallback when disconnected or detecting
    if (!m) {
      m = {
        agent: "AI Agent",
        connected: false,
        status_message: "sin agente conectado",
        session: { total_formatted: "0" },
        context: { used_formatted: "0", limit_formatted: "0", percent: 0 },
        quota_5h: { percent_left: 100, reset_mins: 0 },
        quota_weekly: { percent_left: 100 }
      };
    }

    // DISCONNECTED / NO AGENT VIEW
    if (m.connected === false) {
      return div()
        .w_full()
        .h_full()
        .flex()
        .items_center()
        .justify_between()
        .px(12)
        .bg(t.chrome || "#1e1e1e")
        .text_size(12)
        .child(
          h_flex()
            .gap(12)
            .items_center()
            .child(
              h_flex()
                .gap(6)
                .items_center()
                .child(div().size(6).rounded(3).bg(t.dim || "#737373"))
                .child(
                  div()
                    .text_color(t.dim || "#737373")
                    .child(`${m.agent || "AI Agent"} · ${m.status_message || "sin cuenta / no conectado"}`)
                )
            )
        )
        .child(
          div()
            .text_color(t.dim || "#737373")
            .text_size(11)
            .child(this.hint())
        );
    }

    // CONNECTED VIEW
    const q5h = m.quota_5h || { percent_left: 100, reset_mins: 0 };
    const qWeek = m.quota_weekly || { percent_left: 100 };
    const ctx = m.context || { used_formatted: "0", limit_formatted: "1M", percent: 0 };
    const sess = m.session || { total_formatted: "0" };

    const resetH = Math.floor((q5h.reset_mins || 0) / 60);
    const resetM = (q5h.reset_mins || 0) % 60;
    const resetStr = resetH > 0 ? `${resetH}h ${resetM}m` : `${resetM}m`;

    const color5h = q5h.percent_left > 30 ? t.muted || "#a3a3a3" : q5h.percent_left > 15 ? "#eab308" : t.blocked || "#ef4444";
    const colorWeek = qWeek.percent_left > 30 ? t.muted || "#a3a3a3" : qWeek.percent_left > 15 ? "#eab308" : t.blocked || "#ef4444";
    const colorCtx = ctx.percent > 85 ? t.blocked || "#ef4444" : ctx.percent > 70 ? "#eab308" : t.muted || "#a3a3a3";

    return div()
      .w_full()
      .h_full()
      .flex()
      .items_center()
      .justify_between()
      .px(12)
      .bg(t.chrome || "#1e1e1e")
      .text_size(12)
      .child(
        h_flex()
          .gap(14)
          .items_center()
          .child(
            h_flex()
              .gap(6)
              .items_center()
              .child(div().size(6).rounded(3).bg("#22c55e"))
              .child(
                div()
                  .text_color(t.foreground || "#ffffff")
                  .child(m.model || m.agent || "AI Agent")
              )
          )
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .child(div().text_color(t.dim || "#737373").child("tok:"))
              .child(
                div()
                  .text_color(t.foreground || "#ffffff")
                  .child(sess.total_formatted || "0")
              )
          )
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .child(div().text_color(t.dim || "#737373").child("ctx:"))
              .child(
                div()
                  .text_color(colorCtx)
                  .child(`${ctx.used_formatted || "0"}/${ctx.limit_formatted || "1M"}`)
              )
              .child(
                div()
                  .text_color(t.dim || "#737373")
                  .child(`(${ctx.percent || 0}%)`)
              )
          )
          .child(div().text_color(t.dim || "#525252").child("|"))
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .child(div().text_color(t.dim || "#737373").child("5h:"))
              .child(
                div()
                  .text_color(color5h)
                  .child(`${q5h.percent_left}%`)
              )
              .child(
                div()
                  .text_color(t.dim || "#737373")
                  .child(resetStr)
              )
          )
          .child(
            h_flex()
              .gap(4)
              .items_center()
              .child(div().text_color(t.dim || "#737373").child("sem:"))
              .child(
                div()
                  .text_color(colorWeek)
                  .child(`${qWeek.percent_left}%`)
              )
          )
      )
      .child(
        div()
          .text_color(t.dim || "#737373")
          .text_size(11)
          .child(this.hint())
      );
  }
}
