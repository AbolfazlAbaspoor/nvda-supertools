"""
Build the documentation NVDA shows for the add-on.

    python tools/make_doc.py

Each language has doc/<language>/help.txt, plain text a translator can write
without touching HTML; this turns each one into the readme.html NVDA opens.
English is taken from the add-on itself, so the help on screen and the
documentation can never drift apart.
"""
import html
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "globalPlugins", "superTools.py")
DOC = os.path.join(ROOT, "doc")

TITLE = "SuperTools {version}"
LEAD = ("Keyboard layout repair, spoken-word alerts and process management for NVDA, "
        "all reached from a one-key command mode.")


def version():
    manifest = open(os.path.join(ROOT, "manifest.ini"), encoding="utf-8").read()
    return re.search(r'version\s*=\s*"([^"]+)"', manifest).group(1)


def english_help():
    """The help text as it stands in the add-on, which is the English original."""
    source = open(SOURCE, encoding="utf-8").read()
    opening = 'HELP_TEXT = """\\\n'
    closing = '""".format(ver=CURRENT_VERSION)'
    start = source.index(opening) + len(opening)
    return source[start:source.index(closing, start)]


def as_html(text, title):
    """
    The help as a page: headings, lists and paragraphs, nothing clever.

    A heading is a line with nothing in front of it whose next line is indented.
    That holds in every language, which "it is in capitals" does not: Persian,
    Arabic and Chinese have no capitals at all.
    """
    lines = text.splitlines()
    body, in_list = [], False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or set(stripped) <= set("=-"):
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        heading = (not line.startswith(" ") and following.startswith("  ")
                   and following.strip())
        if heading:
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append("<h2>{}</h2>".format(html.escape(stripped)))
        elif line.startswith(" "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append("<li>{}</li>".format(html.escape(stripped)))
        else:
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append("<p>{}</p>".format(html.escape(stripped)))
    if in_list:
        body.append("</ul>")
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="{}">'.format(title[1]),
        "<head>",
        '<meta charset="utf-8">',
        "<title>{}</title>".format(html.escape(title[0])),
        "</head>",
        "<body>",
        "<h1>{}</h1>".format(html.escape(title[0])),
        "\n".join(body),
        "<h2>LICENCE</h2>",
        "<p>GNU General Public License version 2.</p>",
        "</body>",
        "</html>",
        "",
    ])


def main():
    number = version()

    # English comes from the add-on; keep the file beside it in step.
    english = english_help()
    os.makedirs(os.path.join(DOC, "en"), exist_ok=True)
    with open(os.path.join(DOC, "en", "help.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(english)

    for language in sorted(os.listdir(DOC)) if os.path.isdir(DOC) else []:
        source = os.path.join(DOC, language, "help.txt")
        if not os.path.isfile(source):
            continue
        text = open(source, encoding="utf-8").read().replace("{ver}", number)
        page = as_html(text, (TITLE.format(version=number), language))
        target = os.path.join(DOC, language, "readme.html")
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(page)
        print("{:8} {:4} lines -> doc/{}/readme.html".format(
            language, len(text.splitlines()), language))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
