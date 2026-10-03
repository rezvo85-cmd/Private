# RONN Desktop · Roblox Studio

This is the local desktop shell around RONN R23's existing official Roblox Studio MCP integration.

## What it adds

- one-window Roblox Studio connection status
- automatic local bridge install/start/reconnect while RONN Desktop is open
- live Studio selection and Explorer
- selected-instance context for "fix this" prompts
- visible Inspect → Build → Test results from R23
- user-local Git checkpoints with automatic pre-restore safety checkpoints
- pinned Rokit → Rojo + Wally toolchain installation
- Rojo Studio plugin installation and local Rojo server control
- Electron updater hooks and a Windows NSIS installer target

R23 remains the only planner/brain. The desktop process does not contain provider API keys or a second AI model.

## Development

```bash
npm install
npm run build
npm start
```

For a Windows installer:

```bash
npm run dist:win
```

The installer is unsigned unless a Windows code-signing certificate is configured in CI. Do not claim it is signed until that certificate exists.

## Roblox authorization boundary

RONN can preview saved KeyframeSequence/AnimationClip data in Studio and can install an existing published AnimationId. Permanent Roblox animation publishing remains a user-authorized Roblox operation; the desktop app does not store Roblox account credentials or bypass that boundary.


## BloxBot-derived reliability hardening

RONN Desktop 1.1 reviews and adapts selected reliability patterns from the MIT-licensed BloxBot v0.13.7 project while preserving R23 as RONN's only AI brain.

Added behavior includes:
- resilient StudioMCP discovery across the generated batch target, Roblox registry metadata, version folders, and the newer Roblox Studio folder,
- Explorer fallback across Edit, Server, and Client data models,
- persistent Studio work sessions that become recoverable "interrupted" sessions after a crash or shutdown,
- bounded local diagnostics with secret, email, username, and home-path scrubbing,
- one-click first-run setup for the bridge plus pinned Roblox toolchain.

See `THIRD_PARTY_NOTICES.md` for the BloxBot MIT notice.
