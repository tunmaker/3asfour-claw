// Whisper labels non-speech ("[Music]", "(silence)") and, on near-silent clips,
// invents the endings of YouTube videos. Neither is a request.
const NOISE_LINE = /^\s*[([*][^)\]*]{0,40}[)\]*][\s.]*$/;
const PHANTOMS = new Set(["thank you", "thanks for watching", "thank you for watching",
  "you", "bye", "merci", "sous-titrage st' 501", "sous-titres réalisés para la communauté d'amara.org"]);

export function cleanTranscript(text) {
  const kept = text.split("\n").filter((l) => l.trim() && !NOISE_LINE.test(l)).join(" ").trim();
  return PHANTOMS.has(kept.toLowerCase().replace(/[.!?,\s]+$/, "")) ? "" : kept;
}

// The wake word is in the recording, so it comes back as the first word, spelled
// however whisper heard it: Abbes, Abbas, Abès, Ebbes, Abs, EBS. The exact name is
// always dropped; a near miss only when punctuation follows it, which is how whisper
// writes a vocative, so "Abbey Road" or "Abs workout" survive.
const NAMES = ["abbes", "abbas", "عباس"];
const LEAD = /^\s*(?:(?:hey|ok|okay|يا)[\s,،]+)?([\p{L}\p{M}'’]+)([\s,.!?،؟]*)/iu;

function distance(a, b) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
  }
  return d[a.length][b.length];
}

export function stripName(text) {
  const m = text.match(LEAD);
  if (!m) return text.trim();
  const word = m[1].normalize("NFD").replace(/[\u0300-\u036f\u064B-\u065F]/g, "").toLowerCase();
  const near = Math.min(...NAMES.map((n) => distance(word, n)));
  const punctuated = /[,.!?،؟]/.test(m[2]) || m[0].length === text.length;
  if (word.length >= 3 && (near === 0 || (near <= 2 && punctuated))) return text.slice(m[0].length).trim();
  return text.trim();
}

// The model sometimes thinks out loud in plain text -- "The user said ...",
// "Let me try to parse it" -- before answering or calling a tool. A paragraph that
// opens like that is reasoning and is not spoken; the rest streams as it arrives.
const REASONING = new RegExp("^\\s*(?:(?:okay|ok|so|hmm|alright|well),?\\s+)*(?:" + [
  "the user", "user['’]s", "the (?:voice )?message", "this (?:is|was|looks|seems)",
  "it['’]s (?:just|not|a)", "let me", "let['’]s", "i (?:should|need to|will|['’]ll|must|think|can see)",
  "since (?:this|the)", "looking at", "the (?:transcript|audio|request)", "they (?:said|want|are|asked)",
].join("|") + ")", "i");
const ARABIC = /[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]+/g;

export function isReasoning(text) {
  return REASONING.test(text);
}

// The voice is English; Arabic script would be spelled out letter by letter.
export function speakable(sentence) {
  const clean = sentence.replace(ARABIC, " ").replace(/["“”«»]\s*["“”«»]/g, "").replace(/\s+/g, " ").trim();
  return /[\p{L}\p{N}]/u.test(clean) && !clean.startsWith("⚠") ? clean : "";
}

export class SpokenFilter {
  constructor(Chunker, emit) {
    this.Chunker = Chunker;
    this.emit = emit;
    this.startParagraph();
  }

  startParagraph() {
    this.chunker = new this.Chunker();
    this.pending = "";
    this.mode = "undecided";
  }

  push(delta) {
    const pieces = delta.split(/\n\s*\n/);
    pieces.forEach((piece, i) => {
      if (i > 0) this.endParagraph();
      this.feed(piece);
    });
  }

  feed(text) {
    if (this.mode === "drop" || !text) return;
    if (this.mode === "speak") { this.say(this.chunker.push(text)); return; }
    this.pending += text;
    if (/[.!?:](?:\s|$)/.test(this.pending) || this.pending.length > 120) this.decide();
  }

  decide() {
    this.mode = isReasoning(this.pending) ? "drop" : "speak";
    if (this.mode === "speak") this.say(this.chunker.push(this.pending));
    this.pending = "";
  }

  say(sentences) {
    for (const s of sentences) {
      const clean = speakable(s);
      if (clean) this.emit(clean);
    }
  }

  endParagraph() {
    if (this.mode === "undecided" && this.pending.trim()) this.decide();
    if (this.mode === "speak") this.say(this.chunker.end());
    this.startParagraph();
  }

  end() {
    this.endParagraph();
  }
}
