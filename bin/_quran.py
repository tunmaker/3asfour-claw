import os
import re
import sys
import unicodedata

DATA_DIR = os.environ.get("ABBES_DATA_DIR", "/var/lib/abbes")
SOURCE = os.environ.get("QURAN_FILE", os.path.join(DATA_DIR, "reference/quran/quran-uthmani.txt"))

USAGE = """Usage:
  quran.sh get <sura> <aya>[-<aya>]     retrieve exact ayat
  quran.sh find "<arabic phrase>"       locate ayat containing a phrase

Returns only text present in the source file. Never generates or paraphrases.
"""


def load():
    if not os.path.exists(SOURCE):
        sys.stderr.write(
            "Qur'an source not installed at %s. "
            "Nothing can be quoted. Tell the user the reference text is missing.\n" % SOURCE
        )
        sys.exit(3)
    verses = {}
    with open(SOURCE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 2)
            if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
                continue
            verses[(int(parts[0]), int(parts[1]))] = parts[2]
    if not verses:
        sys.stderr.write("Qur'an source contains no parsable verses.\n")
        sys.exit(3)
    return verses


def strip_marks(text):
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def cmd_get(verses, sura, spec):
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        rng = range(int(lo), int(hi) + 1)
    else:
        rng = [int(spec)]
    missing = [a for a in rng if (sura, a) not in verses]
    if missing:
        sys.stderr.write(
            "Not found in source: sura %d, aya %s. Quote nothing.\n"
            % (sura, ", ".join(str(m) for m in missing))
        )
        sys.exit(4)
    for a in rng:
        print("%d:%d\t%s" % (sura, a, verses[(sura, a)]))


def cmd_find(verses, phrase):
    needle = strip_marks(phrase).strip()
    if len(needle) < 3:
        sys.stderr.write("Search phrase too short.\n")
        sys.exit(2)
    hits = [
        (s, a, t) for (s, a), t in sorted(verses.items()) if needle in strip_marks(t)
    ]
    if not hits:
        sys.stderr.write("No aya in the source contains that phrase. Quote nothing.\n")
        sys.exit(4)
    for s, a, t in hits[:20]:
        print("%d:%d\t%s" % (s, a, t))
    if len(hits) > 20:
        print("... %d more matches not shown" % (len(hits) - 20))


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(USAGE)
        sys.exit(2)
    verses = load()
    action = sys.argv[1]
    if action == "get" and len(sys.argv) == 4:
        cmd_get(verses, int(sys.argv[2]), sys.argv[3])
    elif action == "find" and len(sys.argv) == 3:
        cmd_find(verses, sys.argv[2])
    else:
        sys.stderr.write(USAGE)
        sys.exit(2)


main()
