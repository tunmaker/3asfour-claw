// The vision gate: three tiers, cheapest first.
//
//   1. frame difference   free, every frame. Below threshold, stop here.
//   2. SmolVLM caption    0.36 s of GPU. Only on change. If the caption says the
//                         same thing as last time, stop here.
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

/** 0 = nothing in common, 1 = identical content words. */
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
    timeoutMs = +(process.env.VISION_TIMEOUT_MS || 20000),
    isBusy = () => false,
  } = {}) {
    this.captionUrl = captionUrl;
    this.log = log;
    this.diffThreshold = diffThreshold;
    this.captionSimilarThreshold = captionSimilarThreshold;
    this.minCaptionIntervalMs = minCaptionIntervalMs;
    this.maxCaptionIntervalMs = maxCaptionIntervalMs;
    this.timeoutMs = timeoutMs;
    this.isBusy = isBusy;

    this.lastFrame = null;
    this.lastCaption = null;
    this.lastCaptionAt = 0;
    this.stats = { frames: 0, diffTripped: 0, overdue: 0, captioned: 0, changes: 0, skippedBusy: 0, errors: 0 };
  }

  snapshot() {
    return {
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

    let caption;
    try {
      caption = await this.caption(jpeg, CAPTION_PROMPT);
    } catch (e) {
      this.stats.errors++;
      this.log(`vision: caption failed (${e.message})`);
      return null;
    }
    this.stats.captioned++;
    this.lastCaptionAt = Date.now();

    const previous = this.lastCaption;
    const similarity = captionSimilarity(caption, previous);
    this.lastCaption = caption;

    if (previous && similarity >= this.captionSimilarThreshold) return null;

    this.stats.changes++;
    this.log(`vision: scene changed (diff ${score.toFixed(3)}, similarity ${similarity.toFixed(2)}): ${caption}`);
    return { caption, previous, score, similarity };
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
