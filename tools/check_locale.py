"""
Check the catalogues before building.

    python tools/check_locale.py

Reports anything a translation got wrong that would break at runtime or look
wrong on screen: missing texts, placeholders that were dropped, renamed or
invented, and accelerator keys (&) that disappeared.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_locale

PLACEHOLDER = re.compile(r"\{(\w+)")


def check(language, texts, translations):
    problems = []
    for text in texts:
        translated = translations.get(text)
        if not translated:
            problems.append(("untranslated", text, ""))
            continue
        wanted = sorted(PLACEHOLDER.findall(text))
        got = sorted(PLACEHOLDER.findall(translated))
        if wanted != got:
            problems.append(("placeholders", text, translated))
        elif ("&" in text) != ("&" in translated):
            problems.append(("accelerator", text, translated))
    for text in translations:
        if text not in texts:
            problems.append(("obsolete", text, translations[text]))
    return problems


def main():
    texts = make_locale.source_strings()
    locale = os.path.join(ROOT, "locale")
    failed = False
    for language in sorted(os.listdir(locale)):
        path = os.path.join(locale, language, "LC_MESSAGES", "nvda.po")
        if not os.path.isfile(path):
            continue
        problems = check(language, texts, make_locale.read_po(path))
        missing = [p for p in problems if p[0] == "untranslated"]
        broken = [p for p in problems if p[0] != "untranslated"]
        # A text nobody has translated yet simply appears in English, which is
        # fine; a placeholder that was dropped would break at runtime, so only
        # that kind of problem stops the build.
        print("{:8} {:3}/{} translated{}".format(
            language, len(texts) - len(missing), len(texts),
            ", {} problem(s)".format(len(broken)) if broken else ""))
        for kind, text, translated in broken:
            failed = True
            print("   {:12} {!r}".format(kind, text[:60]))
            if translated:
                print("   {:12} {!r}".format("", translated[:60]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
