// Cut a token stream into speakable sentences.
//
// The point is to hand Piper something as soon as it is worth speaking, without
// ever speaking a fragment that will be contradicted by the next token. So a cut
// only happens on a terminator followed by whitespace. End-of-buffer does not
// count while streaming — the next delta may continue the sentence — so a tail is
// carried until it is terminated or the stream flushes.
//
// Arabic terminators are not the ASCII set: ؟ is the question mark and ؛ the
// semicolon. The comma ، is not a terminator — Derja runs long comma-joined
// clauses — but it IS the preferred place to break an over-long run, because a
// comma is where a speaker would breathe anyway.

const TERMINATORS = new Set([".", "!", "?", "؟", "!", "۔", "؛", ":", "…", "\n"]);
const CLOSERS = new Set(['"', "'", ")", "»", "”", "’", "]", "،"]);

// Never cut when the terminator is doing something other than ending a sentence.
const ABBREV_TAIL = /(?:^|\s)(?:د|م|ص|ب|ج|Dr|Mr|Mrs|St|vs|etc|approx)\.$/i;

function endsMidNumber(buf, i) {
  // "19:09" / "3.5" — digit, terminator, digit
  const prev = buf[i - 1], next = buf[i + 1];
  return prev >= "0" && prev <= "9" && next >= "0" && next <= "9";
}

/**
 * Pull every complete sentence out of `buffer`.
 * Returns { sentences: string[], rest: string } — `rest` is the incomplete tail
 * that must be carried into the next call.
 *
 * `flush` forces the tail out too, for end of stream.
 */
export function cut(buffer, { flush = false, minChars = 2 } = {}) {
  const sentences = [];
  let start = 0;

  for (let i = 0; i < buffer.length; i++) {
    const ch = buffer[i];
    if (!TERMINATORS.has(ch)) continue;
    if (endsMidNumber(buffer, i)) continue;

    // absorb any closing punctuation that belongs to this sentence
    let end = i + 1;
    while (end < buffer.length && CLOSERS.has(buffer[end])) end++;

    // A cut is only safe at whitespace. End-of-buffer is NOT safe while streaming:
    // the next delta may continue the sentence, which is how "19:" + "09." split.
    // Only a flush may cut at the end of what we have.
    const after = buffer[end];
    if (after === undefined) { if (!flush) continue; }
    else if (!/\s/.test(after)) continue;

    const piece = buffer.slice(start, end);
    if (ABBREV_TAIL.test(piece)) continue;
    if (piece.trim().length >= minChars) {
      sentences.push(piece.trim());
      start = end;
      while (start < buffer.length && /\s/.test(buffer[start])) start++;
      i = start - 1;
    }
  }

  let rest = buffer.slice(start);
  if (flush && rest.trim().length) {
    sentences.push(rest.trim());
    rest = "";
  }
  return { sentences, rest };
}

/**
 * Stateful chunker over a delta stream.
 *
 *   const c = new Chunker();
 *   for (const d of deltas) for (const s of c.push(d)) speak(s);
 *   for (const s of c.end()) speak(s);
 *
 * `softLimit` forces a cut on a long run with no terminator — a model that
 * forgets to punctuate must not leave the speaker silent to the end of the turn.
 */
export class Chunker {
  constructor({ firstLimit = 36, softLimit = 180 } = {}) {
    this.buf = "";
    this.firstLimit = firstLimit;
    this.softLimit = softLimit;
    this.emitted = 0;
  }

  // The first chunk is cut hard and short: every character it waits for is silence
  // the household hears. "ماشي،" alone is abrupt on paper but it starts the voice
  // half a second sooner, and Piper stays 18x ahead of playback from then on.
  get limit() { return this.emitted === 0 ? this.firstLimit : this.softLimit; }

  // Break a long run where a speaker would: at the last comma, else the last
  // space. Never mid-word.
  _forceCut() {
    const lim = this.limit;
    if (this.buf.length <= lim) return null;
    const window = this.buf.slice(0, lim);
    let at = Math.max(window.lastIndexOf("،"), window.lastIndexOf(","));
    if (at > 12) return at + 1;
    at = window.lastIndexOf(" ");
    return at > 12 ? at : null;
  }

  push(delta) {
    this.buf += delta;
    const { sentences, rest } = cut(this.buf);
    this.buf = rest;
    this.emitted += sentences.length;

    let at;
    while ((at = this._forceCut()) !== null) {
      const piece = this.buf.slice(0, at).trim();
      if (!piece) break;
      sentences.push(piece);
      this.emitted++;
      this.buf = this.buf.slice(at).replace(/^\s+/, "");
    }
    return sentences;
  }

  replace(text) {
    this.buf = text;
    return [];
  }

  end() {
    const { sentences } = cut(this.buf, { flush: true });
    this.buf = "";
    this.emitted += sentences.length;
    return sentences;
  }
}
