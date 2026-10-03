# RONN Roblox Toolchain

RONN Desktop installs this toolchain into a user-local workspace with Rokit.

Pinned tools:
- Rojo 7.7.1
- Wally 0.3.2

RONN does not automatically add Wally packages to a game. Wally is installed so R23 can use packages only when the user explicitly asks for them.

Rojo is optional for Studio editing because RONN already uses Roblox Studio's official MCP server. Rojo is used for filesystem sync, durable Git checkpoints, diffs, and project recovery.
