# RONN Roblox Studio Bridge

This is RONN's local execution bridge for Roblox Studio's **official MCP server**.

RONN's R23 cloud brain remains the only planner/router/final-answer owner. The local bridge has no model keys and makes no AI decisions. It only:

1. connects to the official Studio MCP over stdio,
2. reports the live MCP tool schemas and connected Studio windows to RONN,
3. polls RONN Core over outbound HTTPS for owner-scoped jobs,
4. injects the exact `studio_id` into every Studio tool call,
5. returns real Studio results for R23 to verify.

## Windows setup

1. Update/open Roblox Studio.
2. In Studio open **Assistant > ... > Manage MCP Servers** and enable **Studio as MCP server**.
3. Run `install_windows.bat` once.
4. In RONN, create a Roblox pairing code.
5. Run `PAIR_AND_RUN_WINDOWS.bat`, enter your RONN URL and the one-time code.
6. Leave the bridge window open while RONN is working in Studio. Later launches can use `RUN_WINDOWS.bat`.

The long bridge token is stored only on this PC under the user's local app-data directory, while RONN Core stores only its SHA-256 hash. Pairing codes expire and can be used once.

## Safety / reliability

- Remote RONN Core URLs must use HTTPS.
- The bridge accepts only the documented Roblox Studio MCP tool allowlist.
- It refuses Studio mutations without an explicit `studio_id`.
- Multiple Studio windows are routed statelessly by their exact Studio instance ID.
- Studio disconnects use bounded reconnect/backoff.
- Cloud jobs have leases and retries so reconnects do not silently lose work.
- No Groq/OpenRouter/NVIDIA keys are stored in this bridge.


## Animation preview workflow

RONN can now handle saved Studio animation data without depending on the RBXMonkey playback UI.

Example request:

`RONN, load RightDash from AnimSaves onto my selected R6 rig, preview it, and verify it moves.`

For animation work, RONN will:

1. inspect the exact selected/named rig and `AnimSaves` clip,
2. check R6/R15 compatibility plus the Humanoid/AnimationController/Animator,
3. preserve the authored KeyframeSequence/AnimationClip and existing combat code,
4. use Roblox Studio's AnimationClipProvider temporary registration path for a Studio-only preview,
5. play the temporary Animation through the inspected Animator,
6. verify the requested rig/clip with Studio evidence instead of assuming a clean Output window means success.

Temporary preview IDs are never written into permanent gameplay code as uploaded Roblox animation asset IDs.

Publishing/uploading an animation is intentionally separate because it requires Roblox account/asset authorization. The Studio MCP preview workflow does not store Roblox credentials or publish assets on its own.
