# Herdr Quota Monitor Recipe

Installs the minimalist real-time token, context window, and 5-hour/weekly quota monitor for coding agents running in Herdr.

## What it does
- Displays current model, session tokens, context window usage, 5-hour quota remaining, and weekly quota remaining in the bottom status bar.
- Automatically synchronizes with the active workspace/project when switching terminals.
- Connects directly to local Antigravity Language Server RPC for exact official account quotas, with extensible adapters for Claude Code, OpenCode, and custom agents.

## Installation Steps for AI Agents
1. Copy `main.js`, `mod.json`, and `collector.py` into `~/.config/herdr-app/mods/agent-quota-bar/`.
2. Copy `main.js` to `~/.config/herdr-app/mods/workspace-status/main.js` to take effect in the active layout immediately.
3. Run `python ~/.config/herdr-app/mods/agent-quota-bar/collector.py` to seed metrics.
4. Run `herdr-app check ~/.config/herdr-app/mods/agent-quota-bar` to verify.
