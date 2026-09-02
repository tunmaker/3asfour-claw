// The vision gate: three tiers, cheapest first.
//
//   1. frame difference   free, every frame. Below threshold, stop here.
//   2. presence question  0.36 s of GPU. Only on change. Fires only when the
//                         yes/no answer FLIPS, not when the wording moves.
//   3. Qwen + mmproj      on demand only, and never during a turn.
//
// Tier 1 alone is not presence detection. It compares compressed size, so it
// responds to the light changing and not to someone sitting still. It decides
// only when to look, never what was seen; tier 2 is what may fire an event, and
// a maximum interval makes sure tier 1 missing something cannot hide it.
//
// The Pi polls the camera about once a second; that cadence is a hardware limit,
// not a choice. Continuous streaming wedges this webcam into EPROTO and takes a
// USB reset plus a driver reload to recover, so a dropped frame is routine here
// and never an error.

const CAPTION_PROMPT =
  process.env.VISION_PROMPT || "Describe this image in one short sentence.";
const PRESENCE_PROMPT =
  process.env.VISION_PRESENCE_PROMPT || "Is a person visible in this image? Answer only yes or no.";

/**
 * How different two JPEGs are, 0..1, by compressed size.
 *
 * There is no JPEG decoder here, so this cannot be a pixel difference. The first
 * version also compared the payloads bytewise and that was worthless: entropy-
 * coded data is not aligned between frames, so the mean absolute byte difference
 * sits near 0.33 whatever the camera is pointed at, and every single frame
 * tripped the gate. Six frames, six trips, on a scene that had not changed.
 *
 * Compressed size is a real signal -- a changed scene codes to a different
 * length. Measured over eight frames of a static room:
 *
 *   consecutive size deltas ... 0.0246 0.0104 0.0108 0.0070 0.0155
 *   max 0.025, mean 0.013
 *
 * so the 0.06 default sits comfortably above the noise floor.
 *
 * This is a suppressor for obviously-unchanged frames, not a change detector: a
 * scene can change without changing size much. Tier 2 is what decides whether
 * anything actually happened, and maxCaptionIntervalMs makes sure tier 1 missing
 * something cannot hide it forever.
 */
export function frameDifference(a, b) {
  if (!a || !b || a.length === 0 || b.length === 0) return 1;
  return Math.abs(a.length - b.length) / Math.max(a.length, b.length);
}

/** Words that carry meaning, for deciding whether two captions say the same thing. */
function contentWords(text) {
  return new Set(
    String(text || "").toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .split(/\s+/)
      .filter((w) => w.length > 3 &&
        !["this", "that", "there", "image", "picture", "with", "have", "from", "which"].includes(w))
  );
}

/**
 * 0 = nothing in common, 1 = identical content words.
 *
 * Kept for the record and for the tests, but no longer what decides a change.
 * Measured over 26 consecutive captions of one static room, consecutive pairs
 * scored min 0.00, median 0.40, max 0.67 -- so at the old 0.70 threshold every
 * single pair counted as a change, 25 out of 25. A free-form caption is a good
 * description and a terrible detector: SmolVLM says "a person sitting on the
 * chair" and then "a man sitting on the chair" about the same unmoved person.
 */
export function captionSimilarity(a, b) {
  const sa = contentWords(a), sb = contentWords(b);
  if (sa.size === 0 && sb.size === 0) return 1;
  if (sa.size === 0 || sb.size === 0) return 0;
  let shared = 0;
  for (const w of sa) if (sb.has(w)) shared++;
  return shared / Math.max(sa.size, sb.size);
}

export class VisionGate {
  constructor({
    captionUrl,
    log = () => {},
    diffThreshold = +(process.env.VISION_DIFF_THRESHOLD || 0.06),
    captionSimilarThreshold = +(process.env.VISION_CAPTION_SIMILARITY || 0.7),
    minCaptionIntervalMs = +(process.env.VISION_MIN_CAPTION_MS || 5000),
    maxCaptionIntervalMs = +(process.env.VISION_MAX_CAPTION_MS || 60000),
    // How many consecutive identical answers before the state flips. One frame
    // where a person is half out of shot should not read as them leaving.
    confirmations = +(process.env.VISION_CONFIRMATIONS || 2),
    timeoutMs = +(process.env.VISION_TIMEOUT_MS || 20000),
    isBusy = () => false,
  } = {}) {
    this.captionUrl = captionUrl;
    this.log = log;
    this.diffThreshold = diffThreshold;
    this.captionSimilarThreshold = captionSimilarThreshold;
    this.minCaptionIntervalMs = minCaptionIntervalMs;
    this.maxCaptionIntervalMs = maxCaptionIntervalMs;
    this.confirmations = Math.max(1, confirmations);
    this.timeoutMs = timeoutMs;
    this.isBusy = isBusy;

    this.lastFrame = null;
    this.lastFrameAt = 0;
    this.lastCaption = null;
    this.lastCaptionAt = 0;
    // null until the first look, so the first answer is not reported as an
    // arrival or a departure.
    this.personPresent = null;
    this.pending = null;
    this.pendingCount = 0;
    this.stats = { frames: 0, diffTripped: 0, overdue: 0, captioned: 0, changes: 0, skippedBusy: 0, errors: 0 };
  }

  snapshot() {
    return {
      personPresent: this.personPresent,
      caption: this.lastCaption,
      capturedAt: this.lastCaptionAt || null,
      ...this.stats,
    };
  }

  /**
   * Offer a frame. Returns null when nothing happened, or
   * {caption, previous, score} when the scene meaningfully changed.
   */
  async offer(jpeg) {
    this.stats.frames++;
    const score = frameDifference(jpeg, this.lastFrame);
    this.lastFrame = jpeg;
    this.lastFrameAt = Date.now();

    // Size can stay flat across a real change, so look anyway if it has been
    // long enough. Tier 1 saves work; it is not allowed to blind the gate.
    const overdue = Date.now() - this.lastCaptionAt >= this.maxCaptionIntervalMs;
    if (score < this.diffThreshold && !overdue) return null;
    if (overdue && score < this.diffThreshold) this.stats.overdue++;
    else this.stats.diffTripped++;

    // Captioning costs GPU that the voice path is also using. A turn in flight
    // always wins; the scene will still be there in a second.
    if (this.isBusy()) { this.stats.skippedBusy++; return null; }
    if (Date.now() - this.lastCaptionAt < this.minCaptionIntervalMs) return null;

    // Ask the closed question, not the open one. "Is a person visible" has a
    // stable answer; "describe this image" has a different answer every time.
    let present;
    try {
      present = await this.personVisible(jpeg);
    } catch (e) {
      this.stats.errors++;
      this.log(`vision: presence check failed (${e.message})`);
      return null;
    }
    this.stats.captioned++;
    this.lastCaptionAt = Date.now();

    const was = this.personPresent;

    // Debounce. The model answers one frame at a time and will occasionally say
    // no about someone who leaned out of shot, which read as them leaving and
    // then arriving 15 seconds later.
    if (present === this.pending) this.pendingCount++;
    else { this.pending = present; this.pendingCount = 1; }
    if (present === was || this.pendingCount < this.confirmations) return null;
    this.personPresent = present;

    // The first observation establishes the baseline rather than announcing it.
    // Otherwise every restart of this process reports an arrival or a departure
    // for a room that has not changed at all.
    if (was === null) {
      this.log(`vision: baseline set, ${present ? "someone is here" : "room is empty"}`);
      return null;
    }

    // Only now is a description worth the tokens, and only because whatever
    // acts on this event needs to know what it is looking at.
    let caption = null;
    try {
      caption = await this.caption(jpeg, CAPTION_PROMPT);
      this.lastCaption = caption;
    } catch { /* the transition is the event; the words are a nicety */ }

    this.stats.changes++;
    const what = present ? "someone arrived" : "the room is empty";
    this.log(`vision: ${what} (diff ${score.toFixed(3)})`);
    return { present, was, caption, previous: this.lastCaption, score };
  }

  /** One question about one frame. Also the tier-3 entry point. */
  async caption(jpeg, prompt = CAPTION_PROMPT, { maxTokens = 40 } = {}) {
    const body = {
      messages: [{
        role: "user",
        content: [
          { type: "image_url", image_url: { url: `data:image/jpeg;base64,${jpeg.toString("base64")}` } },
          { type: "text", text: prompt },
        ],
      }],
      max_tokens: maxTokens,
      temperature: 0,
    };
    const res = await fetch(this.captionUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!res.ok) throw new Error(`caption ${res.status}`);
    const d = await res.json();
    return (d.choices?.[0]?.message?.content || "").trim();
  }

  async personVisible(jpeg) {
    const answer = await this.caption(jpeg, PRESENCE_PROMPT, { maxTokens: 6 });
    return /^\s*yes/i.test(answer);
  }
}
