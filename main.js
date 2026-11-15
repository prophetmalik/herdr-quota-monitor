import { View, div, svg } from "gpui-kit";
import { h_flex } from "gpui-base";
import { spaces, agents, focused, theme, run, window, keys, readTextFile, watchFolder, appHome, exec } from "herdr";

export default class WorkspaceStatus extends View {
  init(_props, cx) {
    this.cache = {};

    const initial = {
      agent: "Antigravity",
      model: "Gemini 3.8 Flash",
      project: "Workspace",
      session: { total_formatted: "0" },
      context: { used_formatted: "0", limit_formatted: "1.0M", percent: 0 },
      quota_5h: { percent_left: 66, reset_mins: 25 },
      quota_weekly: { percent_left: 57 }
    };
    this.metrics = initial;

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

    cx.timer.every(4000, (cx) => this.refresh(cx));
  }

  getActiveInfo() {
    const f = focused();
    const space = spaces().find((s) => s.active);
    const list = agents();
    const activeAgent = list.find((a) => a.pane === f?.pane || a.tab === f?.tab || a.space === space?.id);
    const agentName = activeAgent?.app || activeAgent?.program?.run?.[0] || "";
    const cwd = f?.cwd || space?.folder || "";
    return { cwd, agentName };
  }

  async load(cx) {
    try {
      const p = `${appHome()}/data/agent_quota.json`.replace(/\\/g, "/");
      const txt = await readTextFile(p);
      if (txt) {
        const data = JSON.parse(txt);
        if (data.workspace_cwd) {
          this.cache[data.workspace_cwd] = data;
        }
        const { cwd } = this.getActiveInfo();
        if (this.cache[cwd]) {
          this.metrics = this.cache[cwd];
        } else {
          this.metrics = data;
        }
        cx.notify();
      }
    } catch (_e) {}
  }

  async refresh(cx) {
    const { cwd, agentName } = this.getActiveInfo();
    if (this.cache[cwd]) {
      this.metrics = this.cache[cwd];
      cx.notify();
    } else {
      await this.load(cx);
    }

    try {
      const py = `${appHome()}/mods/agent-quota-bar/collector.py`.replace(/\\/g, "/");
      const args = cwd ? [py, cwd, agentName] : [py];
      await exec("python", args);
      await this.load(cx);
    } catch (_e) {}
  }

  hint(t) {
    const mac = window()?.platform === "macos";
    const mod = { cmd: mac ? "⌘" : "Ctrl+", ctrl: mac ? "⌃" : "Ctrl+", shift: mac ? "⇧" : "Shift+", alt: mac ? "⌥" : "Alt+", option: mac ? "⌥" : "Alt+" };
    const b = keys().find((k) => k.section === "global" && k.action === "app.palette");
    const parts = b && b.keys.endsWith("--") ? [...b.keys.slice(0, -2).split("-"), "-"] : b?.keys.split("-");
    const key = parts && parts.map((p) => mod[p.toLowerCase()] ?? p.toUpperCase()).join("");
    return key ? `${key}  commands` : "commands";
  }

  render() {
    const t = theme();
    const space = spaces().find((s) => s.active);
    const list = agents();
    const needs = list.filter((a) => a.status === "blocked").length;
    const label = (icon, text) =>
      h_flex()
        .gap(6)
        .items_center()
        .child(svg(`mods/workspace-chrome/${icon}.svg`).size(13))
        .child(text);

    const { cwd } = this.getActiveInfo();
    if (cwd && this.cache[cwd]) {
      this.metrics = this.cache[cwd];
    }
    const m = this.metrics || {};
    const q5h = m.quota_5h || { percent_left: 66, reset_mins: 25 };
    const qWeek = m.quota_weekly || { percent_left: 57 };
    const ctx = m.context || { used_formatted: "0", limit_formatted: "1M", percent: 0 };
    const sess = m.session || { total_formatted: "0" };

    const resetH = Math.floor((q5h.reset_mins || 0) / 60);
    const resetM = (q5h.reset_mins || 0) % 60;
    const resetStr = resetH > 0 ? `${resetH}h ${resetM}m` : `${resetM}m`;

    const color5h = q5h.percent_left > 30 ? t.muted : (q5h.percent_left > 15 ? "#eab308" : t.blocked);
    const colorWeek = qWeek.percent_left > 30 ? t.muted : (qWeek.percent_left > 15 ? "#eab308" : t.blocked);

    return h_flex()
      .size_full()
      .px(14)
      .gap(12)
      .items_center()
      .bg(t.chrome)
      .border_t(1)
      .border_color(t.border)
      .text_size(11.8)
      .text_color(t.muted)
      .child(label(space?.machine ? "server" : "monitor", space?.machine ?? "This computer"))
      .when(Boolean(space?.branch), (el) => el.child(label("branch", space.branch)))
      .child(
        h_flex()
          .gap(6)
          .items_center()
          .child(div().size(6).rounded(3).bg(t.dim))
          .child(`${list.length} agents`)
          .when(needs > 0, (el) => el.child(div().text_color(t.blocked).child(`· ${needs} needs you`)))
      )
      .child(div().w(1).h(12).bg(t.border))
      .child(
        h_flex()
          .gap(6)
          .items_center()
          .child(div().size(6).rounded(3).bg(t.accent ?? t.dim))
          .child(div().text_color(t.foreground).child(m.model || "Gemini 3.8 Flash"))
      )
      .child(
        h_flex()
          .gap(4)
          .items_center()
          .child(div().text_color(t.dim).child("tok:"))
          .child(div().text_color(t.foreground).child(sess.total_formatted || "0"))
      )
      .child(
        h_flex()
          .gap(4)
          .items_center()
          .child(div().text_color(t.dim).child("ctx:"))
          .child(div().text_color(t.foreground).child(`${ctx.used_formatted}/${ctx.limit_formatted}`))
          .child(div().text_size(10.5).text_color(t.dim).child(`(${ctx.percent}%)`))
      )
      .child(div().w(1).h(12).bg(t.border))
      .child(
        h_flex()
          .gap(4)
          .items_center()
          .child(div().text_color(t.dim).child("5h:"))
          .child(div().text_color(color5h).child(`${q5h.percent_left}%`))
          .when(q5h.reset_mins > 0, (el) => el.child(div().text_size(10.5).text_color(t.dim).child(`· ${resetStr}`)))
      )
      .child(
        h_flex()
          .gap(4)
          .items_center()
          .child(div().text_color(t.dim).child("sem:"))
          .child(div().text_color(colorWeek).child(`${qWeek.percent_left}%`))
      )
      .child(div().flex_1())
      .child(div().id("palette").text_color(t.dim).on_click(() => run("app.palette")).child(this.hint(t)));
  }
}
