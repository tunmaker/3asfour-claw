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

// The gate, with a stubbed captioner so no model is involved.
async function gateWith(captions, opts = {}) {
  let i = 0;
  const g = new VisionGate({ captionUrl: "http://unused", minCaptionIntervalMs: 0, ...opts });
  g.caption = async () => captions[Math.min(i++, captions.length - 1)];
  return g;
}

// Frames differ by SIZE here, because size is what the metric measures. 8192 vs
// 12000 is a 0.32 change, well over the 0.06 threshold.
const SMALL = Buffer.alloc(8192);
const BIG = Buffer.alloc(12000);
const BIGGER = Buffer.alloc(16000);

{
  const g = await gateWith(["a person at a desk"]);
  ok((await g.offer(SMALL)) !== null, "first frame always looks like a change");
  ok((await g.offer(SMALL)) === null, "an identically sized frame is not a change");
  ok(g.stats.captioned === 1, "the unchanged frame never reached the captioner");
}

{
  const g = await gateWith(["a person at a desk", "a person at a desk", "an empty room"]);
  await g.offer(SMALL);
  const second = await g.offer(BIG);
  ok(second === null, "a changed frame whose caption says the same thing is not a change");
  ok(g.stats.captioned === 2, "but it did cost a caption to find that out");
  const third = await g.offer(BIGGER);
  ok(third !== null && third.caption === "an empty room", "a different caption is a change");
  ok(third.previous === "a person at a desk", "the change carries what it replaced");
}

{
  const g = await gateWith(["anything"], { isBusy: () => true });
  ok((await g.offer(SMALL)) === null, "a live turn suppresses captioning");
  ok(g.stats.captioned === 0 && g.stats.skippedBusy === 1, "and it is counted, not silently dropped");
}

{
  const g = await gateWith([""], { minCaptionIntervalMs: 60000 });
  await g.offer(SMALL);
  const blocked = await g.offer(BIG);
  ok(blocked === null, "the minimum interval holds the captioner off");
  ok(g.stats.captioned === 1, "so the second frame cost nothing");
}

{
  const g = new VisionGate({ captionUrl: "http://unused", minCaptionIntervalMs: 0 });
  g.caption = async () => { throw new Error("model down"); };
  ok((await g.offer(Buffer.alloc(8192))) === null, "a captioner failure is not a change");
  ok(g.stats.errors === 1, "and it is counted");
}

{
  // Size can hold steady across a real change, so the gate must look anyway
  // once it has been quiet too long.
  const g = await gateWith(["a room", "a room with a person in it"],
                           { maxCaptionIntervalMs: 10 });
  await g.offer(Buffer.alloc(8192));
  await new Promise((r) => setTimeout(r, 20));
  const same = Buffer.alloc(8192);
  const out = await g.offer(same);
  ok(out !== null, "an unchanged size still gets looked at once overdue");
  ok(g.stats.overdue === 1, "and it is counted separately from a real trip");
}

{
  const g = await gateWith(["x"], { maxCaptionIntervalMs: 3600000 });
  await g.offer(Buffer.alloc(8192));
  const before = g.stats.captioned;
  await g.offer(Buffer.alloc(8192));
  ok(g.stats.captioned === before, "not overdue and no size change: nothing happens");
  ok(g.stats.overdue === 0, "and nothing is miscounted as overdue");
}

console.log(`vision.test.mjs: ${n} assertions passed`);
