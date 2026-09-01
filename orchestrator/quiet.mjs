// Quiet hours: the one place that decides whether Abbes is allowed to make a
// sound nobody asked for.
//
// This is deliberately not a scheduling feature. Cron already knows how to not
// run at night, and the trigger scripts check the same window before they fire.
// This is the second check, immediately before playback, because the failure
// mode is waking a sleeping household and the causes are not all scheduled: a
// hand-run `cron run`, a webhook from something being tested, an agent that
// decides at 03:00 that it has something useful to say.
//
// A user turn is never blocked. If someone speaks to Abbes at 04:00 they get an
// answer -- they are already awake, and refusing would be a bug, not a courtesy.

import { readFileSync } from "node:fs";

const HHMM = /^([01]?\d|2[0-3]):([0-5]\d)$/;

/** "21:30-07:00" -> {startMin, endMin}, or null when unset or unparseable. */
export function parseWindow(spec) {
  if (!spec) return null;
  const [a, b] = String(spec).trim().split("-");
  const ma = HHMM.exec((a || "").trim());
  const mb = HHMM.exec((b || "").trim());
  if (!ma || !mb) return null;
  const startMin = +ma[1] * 60 + +ma[2];
  const endMin = +mb[1] * 60 + +mb[2];
  if (startMin === endMin) return null;
  return { startMin, endMin, spec: `${a.trim()}-${b.trim()}` };
}

/**
 * Windows that wrap midnight are the normal case here, so the comparison is
 * inclusive of the start and exclusive of the end in both directions.
 */
export function isWithin(win, date = new Date()) {
  if (!win) return false;
  const min = date.getHours() * 60 + date.getMinutes();
  return win.startMin < win.endMin
    ? min >= win.startMin && min < win.endMin
    : min >= win.startMin || min < win.endMin;
}

function fromEnvFile(file, key) {
  try {
    for (const line of readFileSync(file, "utf8").split("\n")) {
      const m = line.match(new RegExp(`^\\s*${key}\\s*=\\s*(.*)$`));
      if (m) return m[1].trim().replace(/^["']|["']$/g, "");
    }
  } catch { /* no env file is not an error; quiet hours are optional */ }
  return null;
}

/**
 * Re-read on every check rather than caching. Editing one line in the env file
 * should take effect now, not after a restart -- that is the whole point of it
 * being one line in one file.
 */
export class QuietHours {
  constructor({ envFile, log = () => {} } = {}) {
    this.envFile = envFile;
    this.log = log;
    this.lastSpec = undefined;
  }

  window() {
    // File first, process.env second. systemd loads the same file into the
    // environment at start, so checking process.env first would pin the value
    // to whenever the service last restarted -- which is exactly the thing this
    // is meant to avoid. The file is the knob; the environment is the fallback
    // for running this outside systemd.
    const spec = fromEnvFile(this.envFile, "QUIET_HOURS") ?? process.env.QUIET_HOURS;
    const win = parseWindow(spec);
    if (spec !== this.lastSpec) {
      this.lastSpec = spec;
      if (spec && !win) this.log(`quiet hours: ignoring unparseable QUIET_HOURS=${JSON.stringify(spec)}`);
      else this.log(win ? `quiet hours: ${win.spec}` : "quiet hours: not configured");
    }
    return win;
  }

  /** True when unprompted speech must be refused right now. */
  blocks(date = new Date()) {
    return isWithin(this.window(), date);
  }

  nightVolume() {
    const raw = fromEnvFile(this.envFile, "SPEAKER_NIGHT_VOLUME") ?? process.env.SPEAKER_NIGHT_VOLUME;
    const n = Number.parseInt(raw ?? "", 10);
    return Number.isFinite(n) && n >= 0 && n <= 100 ? n : null;
  }
}
