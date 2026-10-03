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
