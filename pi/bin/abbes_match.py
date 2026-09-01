"""Deciding whether a piece of text contains the name.

Pure text, no audio and no model, so the same rules apply wherever the decision
is made. This exists as its own module because the wake word now runs on the
server rather than the Pi: two copies of "what counts as عبّاس" would eventually
disagree, and the disagreement would show up as the assistant ignoring someone.
"""
import pathlib
import re
import unicodedata

DIACRITICS = re.compile(r"[ً-ْٰـ]")
ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})
NONWORD = re.compile(r"[^\w]+", re.UNICODE)

DEFAULT_GRAMMAR = ["عباس", "يا عباس", "abbes"]
DEFAULT_CANDIDATES = ["عباس", "عبّاس", "abbes", "abbas", "abes"]


def normalize(text):
    """Fold diacritics, alef forms and Latin accents so variants compare equal."""
    text = DIACRITICS.sub("", text).translate(ALEF)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return NONWORD.sub(" ", text.lower()).strip()


def within(a, b, k):
    if abs(len(a) - len(b)) > k:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > k:
            return False
        prev = cur
    return prev[-1] <= k


class Matcher:
    """Accepts a phrase when every word is within `fuzz` edits of a candidate."""

    def __init__(self, candidates, fuzz=1):
        self.candidates = [normalize(c).split() for c in candidates if c.strip()]
        self.fuzz = fuzz

    def find(self, text):
        words = normalize(text).split()
        for candidate in self.candidates:
            n = len(candidate)
            for i in range(len(words) - n + 1):
                window = words[i:i + n]
                if all(within(w, c, self.fuzz) for w, c in zip(window, candidate)):
                    return " ".join(window)
        return None

    def strip(self, text):
        """Remove the trigger from a transcript so only the request is forwarded."""
        words = text.split()
        normalized = [normalize(w) for w in words]
        for candidate in self.candidates:
            n = len(candidate)
            for i in range(len(words) - n + 1):
                if all(within(w, c, self.fuzz) for w, c in zip(normalized[i:i + n], candidate)):
                    lead = words[:i]
                    if lead and normalize(lead[-1]) in ("يا", "ya"):
                        lead = lead[:-1]
                    return " ".join(lead + words[i + n:]).strip(" ،,.!؟?")
        return text


def load_decoys(path, model_path=None):
    """Competing words. Without them the decoder has only the name to choose
    from and fires on any speech at all.

    Words outside the model's vocabulary cannot be decoded, so they are dropped
    here rather than left for Vosk to warn about on every start.
    """
    if not path:
        return []
    p = pathlib.Path(path).expanduser()
    if not p.is_file():
        return []
    words = [w for line in p.read_text(encoding="utf-8").splitlines()
             if not line.strip().startswith("#") for w in line.split()]
    vocab = pathlib.Path(model_path or "") / "graph" / "words.txt"
    if vocab.is_file():
        known = {line.split()[0] for line in vocab.read_text(encoding="utf-8").splitlines() if line.strip()}
        words = [w for w in words if w in known]
    return words
