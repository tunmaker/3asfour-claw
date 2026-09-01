#!/usr/bin/env python3
"""CLI for _baby.py. See baby.sh for usage."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _baby  # noqa: E402


def report(stored, assumed, extra=None):
    for a in assumed:
        print(f"افتراض: {a}")
    if extra:
        print(extra)
    print(f"STORED: {stored}")


def main(argv):
    cfg = _baby.settings()
    imported = _baby.import_legacy(cfg)
    if imported:
        print(f"imported {imported} legacy rows", file=sys.stderr)
    cmd = argv[1] if len(argv) > 1 else "today"
    rest = argv[2:]
    try:
        if cmd == "feed":
            ml = int(rest[0]) if rest and rest[0].isdigit() else None
            note = " ".join(rest[1:] if ml is not None else rest)
            report(*_baby.feed(cfg, ml, note))
        elif cmd == "sleep":
            times = [a for a in rest[:2] if _baby.is_hhmm(a)]
            note = " ".join(rest[len(times):])
            report(*_baby.sleep(cfg, *times, note=note))
        elif cmd == "wake":
            at = rest[0] if rest and _baby.is_hhmm(rest[0]) else None
            note = " ".join(rest[1:] if at else rest)
            stored, assumed, minutes = _baby.wake(cfg, at, note)
            report(stored, assumed, f"نام {minutes // 60} ساعة و{minutes % 60} دقيقة")
        elif cmd == "diaper":
            state = rest[0] if rest and rest[0] in _baby.DIAPER else None
            note = " ".join(rest[1:] if state else rest)
            report(*_baby.diaper(cfg, state, note))
        elif cmd == "note":
            report(*_baby.note(cfg, " ".join(rest)))
        elif cmd == "today":
            print(_baby.summary(cfg, 1))
        elif cmd == "last":
            print(_baby.last(cfg))
        elif cmd == "list":
            print(_baby.listing(cfg, int(rest[0]) if rest and rest[0].isdigit() else 1))
        elif cmd == "summary":
            print(_baby.summary(cfg, int(rest[0]) if rest and rest[0].isdigit() else 7))
        else:
            print(f"unknown command {cmd}; one of feed sleep wake diaper note today last list summary", file=sys.stderr)
            return 2
        return 0
    except _baby.JournalError as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
