"""
Build the gettext catalogues the add-on ships.

    python tools/make_locale.py

It scans globalPlugins/superTools.py for _("...") calls, writes locale/nvda.pot,
merges every existing locale/<lang>/LC_MESSAGES/nvda.po with it (keeping the
translations, dropping what is gone, adding what is new) and compiles each one
to nvda.mo, which is what NVDA reads at runtime.

Nothing outside the standard library is needed.
"""
import array
import ast
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "globalPlugins", "superTools.py")
LOCALE = os.path.join(ROOT, "locale")

POT_HEADER = '''msgid ""
msgstr ""
"Project-Id-Version: SuperTools\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: {language}\\n"
"Last-Translator: {translator}\\n"
"Language-Team: {name}\\n"
'''

# The name of each language as its own speakers write it, used in the credits.
LANGUAGE_NAMES = {
    "ar": "العربية", "de": "Deutsch", "en": "English", "es": "Español",
    "fa": "فارسی", "fr": "Français", "it": "Italiano", "pt": "Português",
    "ru": "Русский", "tr": "Türkçe", "zh_CN": "简体中文",
}


def source_strings():
    """Every English text passed to _() in the add-on, in the order it appears."""
    tree = ast.parse(open(SOURCE, encoding="utf-8").read())
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            text = node.args[0].value
            if text not in found:
                found.append(text)
    return found


def po_escape(text):
    return (text.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\n", "\\n").replace("\t", "\\t"))


def po_unescape(text):
    return (text.replace('\\n', "\n").replace('\\t', "\t")
                .replace('\\"', '"').replace("\\\\", "\\"))


def read_header(path, field):
    """One header field of a .po file, such as Last-Translator."""
    marker = '"' + field + ": "
    for line in open(path, encoding="utf-8"):
        if line.strip().startswith(marker):
            value = line.strip()[len(marker):].rstrip('"')
            # The value ends with a literal backslash-n inside the quotes, and a
            # rewritten file can carry more than one of them.
            while value.endswith("\\n"):
                value = value[:-2]
            return value.strip()
    return ""


def read_po(path):
    """{msgid: msgstr} from a .po file; enough for the files we write ourselves."""
    entries = {}
    msgid = msgstr = None
    target = None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("msgid "):
            if msgid is not None:
                entries[msgid] = msgstr or ""
            msgid, target = po_unescape(line[7:-1]), "id"
            msgstr = None
        elif line.startswith("msgstr "):
            msgstr, target = po_unescape(line[8:-1]), "str"
        elif line.startswith('"') and line.endswith('"'):
            chunk = po_unescape(line[1:-1])
            if target == "id":
                msgid += chunk
            elif target == "str":
                msgstr = (msgstr or "") + chunk
        elif not line:
            target = None
    if msgid is not None:
        entries[msgid] = msgstr or ""
    entries.pop("", None)
    return entries


def write_po(path, language, texts, translations, translator="", name=""):
    lines = [POT_HEADER.format(language=language, translator=translator,
                               name=name or LANGUAGE_NAMES.get(language, language))]
    for text in texts:
        lines.append('\nmsgid "{}"\nmsgstr "{}"\n'.format(
            po_escape(text), po_escape(translations.get(text, ""))))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(lines))


def write_mo(path, catalog):
    """Compile a catalogue, in the .mo layout gettext expects."""
    items = sorted((k, v) for k, v in catalog.items() if v)
    items.insert(0, ("", "Content-Type: text/plain; charset=UTF-8\n"))
    ids = strs = b""
    offsets = []
    for msgid, msgstr in items:
        encoded_id, encoded_str = msgid.encode("utf-8"), msgstr.encode("utf-8")
        offsets.append((len(ids), len(encoded_id), len(strs), len(encoded_str)))
        ids += encoded_id + b"\0"
        strs += encoded_str + b"\0"
    key_start = 7 * 4 + 16 * len(items)
    value_start = key_start + len(ids)
    key_offsets, value_offsets = [], []
    for id_offset, id_length, str_offset, str_length in offsets:
        key_offsets += [id_length, id_offset + key_start]
        value_offsets += [str_length, str_offset + value_start]
    output = struct.pack("Iiiiiii", 0x950412de, 0, len(items),
                         7 * 4, 7 * 4 + len(items) * 8, 0, 0)
    output += array.array("i", key_offsets + value_offsets).tobytes()
    output += ids + strs
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(output)


def main():
    texts = source_strings()
    write_po(os.path.join(LOCALE, "nvda.pot"), "xx", texts, {})
    print("{:10} {:4} texts -> locale/nvda.pot".format("template", len(texts)))

    known = set(texts)
    credits = {}
    for language in sorted(os.listdir(LOCALE)) if os.path.isdir(LOCALE) else []:
        po_path = os.path.join(LOCALE, language, "LC_MESSAGES", "nvda.po")
        if not os.path.isfile(po_path):
            continue
        translations = read_po(po_path)
        stale = [text for text in translations if text not in known]
        translator = read_header(po_path, "Last-Translator")
        name = read_header(po_path, "Language-Team") or LANGUAGE_NAMES.get(language, language)
        # A language is often several people's work; the header holds them all,
        # separated by commas, in the order they worked on it.
        people = [who.strip() for who in translator.split(",") if who.strip()]
        credits[language] = {"language": name, "translators": people,
                             "translator": translator}
        write_po(po_path, language, texts, translations, translator, name)
        write_mo(os.path.join(LOCALE, language, "LC_MESSAGES", "nvda.mo"), translations)
        done = sum(1 for text in texts if translations.get(text))
        print("{:10} {:4}/{} translated{}".format(
            language, done, len(texts),
            ", {} obsolete dropped".format(len(stale)) if stale else ""))

    # What the add-on shows as "who made this", and the list for the repository.
    with open(os.path.join(LOCALE, "credits.json"), "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1, sort_keys=True)
    lines = ["# Translators", "",
             "SuperTools speaks the language NVDA is set to. These are the people who",
             "made that possible; a language can be the work of several, and they are",
             "all listed. To add or improve a language, see CONTRIBUTING.md.", "",
             "| Language | Translated by |", "| --- | --- |"]
    for language in sorted(credits):
        entry = credits[language]
        lines.append("| {} ({}) | {} |".format(entry["language"], language,
                                               ", ".join(entry["translators"]) or "-"))
    with open(os.path.join(ROOT, "TRANSLATORS.md"), "w", encoding="utf-8", newline=chr(10)) as f:
        f.write(chr(10).join(lines) + chr(10))
    print("{:10} {} languages -> locale/credits.json, TRANSLATORS.md".format("credits", len(credits)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
