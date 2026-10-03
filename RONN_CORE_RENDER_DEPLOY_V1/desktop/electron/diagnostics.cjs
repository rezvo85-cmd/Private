const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const MAX_ENTRIES = 200;
const MAX_MESSAGE = 1200;
const MAX_STACK = 5000;
const DEDUPE_MS = 60000;

const SECRET_PATTERNS = [
  [/\b(Bearer|Basic|Token)\s+[A-Za-z0-9._~+/=-]{8,}/gi, "$1 [redacted]"],
  [/\bsk-[A-Za-z0-9_-]{12,}/g, "[redacted]"],
  [/\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})/g, "[redacted]"],
  [/\b(?:gsk|xai|pplx|hf|glpat|npm)[_-][A-Za-z0-9_-]{16,}/g, "[redacted]"],
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, "[redacted]"],
  [/\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b/g, "<email>"],
  [/\b((?:api[_-]?key|token|secret|password|passwd|authorization|credential)s?)(\s*[:=]\s*)([^\s"',;&)}]+)/gi, "$1$2[redacted]"],
];

function replaceAllInsensitive(text, value, replacement) {
  if (!value || value.length < 3) return text;
  return text.split(value).join(replacement);
}

function scrub(value, home, username, limit = MAX_MESSAGE) {
  let text = String(value == null ? "" : value);
  text = replaceAllInsensitive(text, home, "~");
  text = replaceAllInsensitive(text, username, "<user>");
  text = text.replace(/(?:[A-Za-z]:)?[\\/](?:Users|home)[\\/][^\\/\r\n"'<>|:*?]+/gi, "~");
  for (const [pattern, replacement] of SECRET_PATTERNS) text = text.replace(pattern, replacement);
  if (text.length > limit) text = text.slice(0, Math.max(0, limit - 1)) + "…";
  return text;
}

class Diagnostics {
  constructor(userData) {
    this.file = path.join(userData, "diagnostics.json");
    this.home = os.homedir();
    this.username = (() => { try { return os.userInfo().username; } catch { return ""; } })();
    this.lastSeen = new Map();
  }

  read() {
    try {
      const data = JSON.parse(fs.readFileSync(this.file, "utf8"));
      return Array.isArray(data?.entries) ? data.entries : [];
    } catch {
      return [];
    }
  }

  write(entries) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const payload = JSON.stringify({ version: 1, entries: entries.slice(0, MAX_ENTRIES) }, null, 2);
    fs.writeFileSync(this.file, payload, "utf8");
  }

  report(source, error, meta = {}) {
    try {
      const rawMessage = error instanceof Error ? error.message : String(error == null ? "Unknown error" : error);
      const name = error instanceof Error ? error.name : "Error";
      const message = scrub(rawMessage, this.home, this.username);
      const key = source + "\u0000" + name + "\u0000" + message;
      const now = Date.now();
      const prior = this.lastSeen.get(key);
      if (prior && now - prior < DEDUPE_MS) return null;
      this.lastSeen.set(key, now);
      if (this.lastSeen.size > 250) {
        for (const [entry, seen] of this.lastSeen) if (now - seen >= DEDUPE_MS) this.lastSeen.delete(entry);
      }

      const entry = {
        at: now,
        source: scrub(source, this.home, this.username, 160),
        name: scrub(name, this.home, this.username, 120),
        message,
        stack: error instanceof Error && error.stack ? scrub(error.stack, this.home, this.username, MAX_STACK) : "",
        meta: {
          phase: scrub(meta.phase || "", this.home, this.username, 120),
          code: scrub(meta.code || "", this.home, this.username, 120),
        },
      };
      const entries = this.read();
      entries.unshift(entry);
      this.write(entries);
      return entry;
    } catch {
      return null;
    }
  }

  list(limit = 80) {
    return this.read().slice(0, Math.max(1, Math.min(Number(limit || 80), MAX_ENTRIES)));
  }

  clear() {
    this.write([]);
    return { ok: true };
  }
}

module.exports = { Diagnostics, scrub };
