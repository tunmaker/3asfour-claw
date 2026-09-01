// node vision.test.mjs
import assert from "node:assert";
import { frameDifference, captionSimilarity, VisionGate } from "./vision.mjs";

let n = 0;
const ok = (c, m) => { assert.ok(c, m); n++; };
const buf = (...bytes) => Buffer.from(bytes);

// frameDifference
ok(frameDifference(null, buf(1, 2, 3)) === 1, "no previous frame is a full change");
ok(frameDifference(buf(1, 2, 3), null) === 1, "no current frame is a full change");
ok(frameDifference(Buffer.alloc(0), buf(1)) === 1, "empty is a full change");
ok(frameDifference(buf(...Array(4096).fill(10)), buf(...Array(4096).fill(10))) === 0,
   "same-size frames score zero");
ok(frameDifference(Buffer.alloc(4096, 0), Buffer.alloc(4096, 255)) === 0,
   "content is invisible to this: it measures compressed size, not pixels");
ok(frameDifference(Buffer.alloc(10000, 7), Buffer.alloc(5000, 7)) === 0.5,
   "a halved payload is a half-scale change");
{
  // The measured static-scene noise floor: eight consecutive frames of an
  // unchanged room never exceeded 0.025, so the 0.06 default clears it.
  const sizes = [54214, 55583, 56166, 56178, 55571, 55963, 55094];
  const worst = Math.max(...sizes.slice(1).map((s, i) =>
    frameDifference(Buffer.alloc(s), Buffer.alloc(sizes[i]))));
  ok(worst < 0.06, `measured static-scene frames stay under the threshold (${worst.toFixed(4)})`);
}

// captionSimilarity
ok(captionSimilarity("a person sitting at a desk", "a person sitting at a desk") === 1,
   "identical captions");
ok(captionSimilarity("", "") === 1, "two empty captions are the same nothing");
ok(captionSimilarity("a person at a desk", "") === 0, "something vs nothing");
ok(captionSimilarity("a monitor, a keyboard and a table",
                     "a monitor, a keyboard and a curtain") > 0.4,
   "mostly-shared captions score high");
ok(captionSimilarity("a person standing in a doorway",
                     "an empty kitchen with cupboards") < 0.3,
   "different scenes score low");
ok(captionSimilarity("In this image there is a screen.",
                     "In this picture there is a screen.") === 1,
   "filler words are ignored, so this and picture do not count as a change");

// The gate, with the model stubbed out. `presence` is the sequence of yes/no
// answers the presence question would give; the caption is incidental now.
async function gateWith(presence, opts = {}) {
  let i = 0;
  const g = new VisionGate({ captionUrl: "http://unused", minCaptionIntervalMs: 0, ...opts });
  g.personVisible = async () => presence[Math.min(i++, presence.length - 1)];
  g.caption = async () => "a room";
  return g;
}

// Frames differ by SIZE here, because size is what the metric measures. 8192 vs
// 12000 is a 0.32 change, well over the 0.06 threshold.
const SMALL = Buffer.alloc(8192);
const BIG = Buffer.alloc(12000);
const BIGGER = Buffer.alloc(16000);

{
  // The first observation is a baseline, not an event. Reporting it would make
  // every restart of the orchestrator announce an arrival into an unchanged room.
  const g = await gateWith([true, true], { confirmations: 1 });
  ok((await g.offer(SMALL)) === null, "the first look sets the baseline silently");
  ok(g.personPresent === true, "but the state is recorded");
  ok((await g.offer(SMALL)) === null, "an identically sized frame is not looked at");
  ok(g.stats.captioned === 1, "so the model was asked exactly once");
}

{
  // One dissenting frame is not a departure. Measured: the model said no about
  // someone who had leaned out of shot, and the gate reported them leaving and
  // arriving again 15 seconds later.
  const g = await gateWith([true, true, false, true, true], { confirmations: 2 });
  await g.offer(SMALL); await g.offer(BIG);          // baseline: present
  ok(g.personPresent === true, "baseline is present");
  ok((await g.offer(BIGGER)) === null, "a single 'no' does not flip the state");
  ok(g.personPresent === true, "still present after one dissent");
  ok((await g.offer(SMALL)) === null, "and back to yes is a non-event");
  ok(g.stats.changes === 0, "the flicker produced no events at all");
}

{
  const g = await gateWith([true, true, false, false], { confirmations: 2 });
  await g.offer(SMALL); await g.offer(BIG);
  await g.offer(BIGGER);
  const left = await g.offer(SMALL);
  ok(left !== null && left.present === false, "two agreeing frames do flip it");
  ok(left.was === true, "and it carries what it was before");
}

{
  // The failure this replaced: SmolVLM rewords the same room every time, and
  // 25 of 25 consecutive real captions scored under the old 0.70 threshold. A
  // yes/no answer does not drift.
  const g = await gateWith([true, true, true, true, false, false], { confirmations: 2 });
  await g.offer(SMALL);
  ok((await g.offer(BIG)) === null, "still there: a changed frame is not an event");
  ok((await g.offer(BIGGER)) === null, "still there again");
  await g.offer(SMALL);
  await g.offer(BIG);
  const left = await g.offer(BIGGER);
  ok(left !== null && left.present === false, "the room emptying is an event");
  ok(g.stats.changes === 1, "one event, not one per rewording");
}

{
  const g = await gateWith([true], { isBusy: () => true });
  ok((await g.offer(SMALL)) === null, "a live turn suppresses captioning");
  ok(g.stats.captioned === 0 && g.stats.skippedBusy === 1, "and it is counted, not silently dropped");
}

{
  const g = await gateWith([true], { minCaptionIntervalMs: 60000 });
  await g.offer(SMALL);
  const blocked = await g.offer(BIG);
  ok(blocked === null, "the minimum interval holds the captioner off");
  ok(g.stats.captioned === 1, "so the second frame cost nothing");
}

{
  const g = new VisionGate({ captionUrl: "http://unused", minCaptionIntervalMs: 0 });
  g.personVisible = async () => { throw new Error("model down"); };
  ok((await g.offer(Buffer.alloc(8192))) === null, "a model failure is not a change");
  ok(g.stats.errors === 1, "and it is counted");
}

{
  // Size can hold steady across a real change, so the gate must look anyway
  // once it has been quiet too long.
  const g = await gateWith([false, true, true], { maxCaptionIntervalMs: 10, confirmations: 1 });
  await g.offer(Buffer.alloc(8192));
  await new Promise((r) => setTimeout(r, 20));
  const same = Buffer.alloc(8192);
  const out = await g.offer(same);
  ok(out !== null, "an unchanged size still gets looked at once overdue");
  ok(g.stats.overdue === 1, "and it is counted separately from a real trip");
}

{
  const g = await gateWith([true], { maxCaptionIntervalMs: 3600000, confirmations: 1 });
  await g.offer(Buffer.alloc(8192));
  const before = g.stats.captioned;
  await g.offer(Buffer.alloc(8192));
  ok(g.stats.captioned === before, "not overdue and no size change: nothing happens");
  ok(g.stats.overdue === 0, "and nothing is miscounted as overdue");
}

console.log(`vision.test.mjs: ${n} assertions passed`);
