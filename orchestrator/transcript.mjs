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
const NAMES = ["abbes", "abbas"];
const LEAD = /^\s*(?:(?:hey|ok|okay)[\s,]+)?([\p{L}'’]+)([\s,.!?]*)/iu;

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
  const word = m[1].normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const near = Math.min(...NAMES.map((n) => distance(word, n)));
  const punctuated = /[,.!?]/.test(m[2]) || m[0].length === text.length;
  if (word.length >= 3 && (near === 0 || (near <= 2 && punctuated))) return text.slice(m[0].length).trim();
  return text.trim();
}
