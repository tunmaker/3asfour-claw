// node quiet.test.mjs
import assert from "node:assert";
import { parseWindow, isWithin } from "./quiet.mjs";

let n = 0;
const at = (h, m) => new Date(2026, 8, 1, h, m, 0);
const ok = (c, msg) => { assert.ok(c, msg); n++; };

// parsing
assert.deepEqual(parseWindow("21:30-07:00").startMin, 21 * 60 + 30); n++;
assert.deepEqual(parseWindow("21:30-07:00").endMin, 7 * 60); n++;
assert.equal(parseWindow(""), null); n++;
assert.equal(parseWindow(null), null); n++;
assert.equal(parseWindow("nonsense"), null); n++;
assert.equal(parseWindow("25:00-07:00"), null, "hour out of range"); n++;
assert.equal(parseWindow("21:70-07:00"), null, "minute out of range"); n++;
assert.equal(parseWindow("07:00-07:00"), null, "empty window is not a window"); n++;
assert.equal(parseWindow("7:00-19:30").startMin, 7 * 60, "single-digit hour"); n++;

// the window that wraps midnight -- the normal case
const night = parseWindow("21:30-07:00");
ok(isWithin(night, at(23, 0)), "before midnight");
ok(isWithin(night, at(0, 0)), "midnight exactly");
ok(isWithin(night, at(3, 14)), "small hours");
ok(isWithin(night, at(21, 30)), "start is inclusive");
ok(isWithin(night, at(6, 59)), "last minute before the end");
ok(!isWithin(night, at(7, 0)), "end is exclusive");
ok(!isWithin(night, at(12, 0)), "midday");
ok(!isWithin(night, at(21, 29)), "one minute before the start");

// a window that does not wrap, for the case someone inverts it
const day = parseWindow("09:00-17:00");
ok(isWithin(day, at(9, 0)), "non-wrapping start inclusive");
ok(isWithin(day, at(16, 59)), "non-wrapping inside");
ok(!isWithin(day, at(17, 0)), "non-wrapping end exclusive");
ok(!isWithin(day, at(3, 0)), "non-wrapping excludes the night");

// unset means never blocked
ok(!isWithin(null, at(3, 0)), "no window blocks nothing");

console.log(`quiet.test.mjs: ${n} assertions passed`);

// The env file is authoritative when it exists. systemd loads it into the
// process environment at start, so a key commented out in the file must not
// keep resolving to what it held at the last restart -- especially this one,
// which grants permission to speak at night.
import { QuietHours } from "./quiet.mjs";
import { writeFileSync, unlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const envPath = join(tmpdir(), `quiet-test-${process.pid}.env`);
process.env.QUIET_HOURS_EXEMPT = "stale:from-environment";

writeFileSync(envPath, "QUIET_HOURS=21:30-07:00\n# QUIET_HOURS_EXEMPT=cron:x\n");
const q = new QuietHours({ envFile: envPath });
assert.deepEqual([...q.exempt()], [], "commented-out key means none, not the stale environment");
assert.equal(q.window().spec, "21:30-07:00");
assert.ok(q.blocks("cron:x", new Date(2026, 8, 1, 23, 0)), "not exempt, so blocked");

writeFileSync(envPath, "QUIET_HOURS=21:30-07:00\nQUIET_HOURS_EXEMPT=cron:x\n");
assert.deepEqual([...q.exempt()], ["cron:x"], "uncommenting takes effect with no restart");
assert.ok(!q.blocks("cron:x", new Date(2026, 8, 1, 23, 0)), "exempt source speaks at night");
assert.ok(q.blocks("cron:other", new Date(2026, 8, 1, 23, 0)), "a different source is still blocked");
assert.ok(!q.blocks("cron:other", new Date(2026, 8, 1, 12, 0)), "midday blocks nobody");

unlinkSync(envPath);
assert.deepEqual([...new QuietHours({ envFile: envPath }).exempt()], ["stale:from-environment"],
  "with no file at all, the environment is the only source there is");

console.log("quiet.test.mjs: 7 further assertions on env-file precedence passed");
