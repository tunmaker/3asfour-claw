// Whisper labels non-speech ("[Music]", "(silence)") and, on near-silent clips,
// invents the endings of YouTube videos. Neither is a request.
const NOISE_LINE = /^\s*[([*][^)\]*]{0,40}[)\]*][\s.]*$/;
const PHANTOMS = new Set(["thank you", "thanks for watching", "thank you for watching",
  "you", "bye", "merci", "sous-titrage st' 501", "sous-titres réalisés para la communauté d'amara.org"]);

export function cleanTranscript(text) {
  const kept = text.split("\n").filter((l) => l.trim() && !NOISE_LINE.test(l)).join(" ").trim();
  return PHANTOMS.has(kept.toLowerCase().replace(/[.!?,\s]+$/, "")) ? "" : kept;
}

// The wake word is in the recording, so it comes back in the transcript.
// Whisper spells it several ways; only a leading occurrence is dropped.
const NAME = /^\s*(?:hey\s+|ok\s+|okay\s+)?ab{1,2}[aeéèê]s{1,2}(?=[\s,.!?]|$)[\s,.!?]*/i;

export function stripName(text) {
  return text.replace(NAME, "").trim();
}
