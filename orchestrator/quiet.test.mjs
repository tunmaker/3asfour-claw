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
