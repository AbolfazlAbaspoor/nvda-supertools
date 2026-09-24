# -*- coding: utf-8 -*-
# SuperTools for NVDA v3.2.0
# GPL v2

import globalPluginHandler
import api
import ui
import scriptHandler
import textInfos
import addonHandler
import config
import gui
import wx
import ctypes
import time
import threading
import speech
import speechViewer
import tones
import versionInfo
import os
import re
import gc
import json
import subprocess
import tempfile
import globalVars
from logHandler import log
from ctypes import wintypes

addonHandler.initTranslation()

BUILD_YEAR            = getattr(versionInfo, 'version_year', 2021)
DOUBLE_PRESS_INTERVAL = 0.5
CFG                   = "superTools"
def _read_version():
    """The version, taken from manifest.ini so it is written down in one place."""
    try:
        manifest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "manifest.ini")
        for line in open(manifest, encoding="utf-8"):
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return "0.0.0"

CURRENT_VERSION       = _read_version()

def _read_author():
    """The author, from the manifest, without the address."""
    try:
        manifest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "manifest.ini")
        for line in open(manifest, encoding="utf-8"):
            if line.strip().startswith("author"):
                name = line.split("=", 1)[1].strip().strip('"\'')
                return name.split("<")[0].strip() or name
    except Exception:
        pass
    return "Abolfazl Abaspoor"

ADDON_AUTHOR          = _read_author()

# The running GlobalPlugin instance.
_plugin = None

# ── Translations ──────────────────────────────────────────────────
# addonHandler.initTranslation() above put _() into this module: it translates
# the English text through locale/<language>/LC_MESSAGES/nvda.mo, following the
# language NVDA itself runs in. This guard only matters outside NVDA (tests).
if "_" not in dir():
    def _(text):
        return text

def _addon_dir():
    """The add-on folder: the parent of globalPlugins."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _nvda_language():
    """The language NVDA itself runs in, as a plain code such as "fa"."""
    try:
        import languageHandler
        return str(languageHandler.getLanguage() or "en").replace("-", "_").lower()
    except Exception:
        return "en"

def _credits():
    """
    Who translated the language in use and who made the chosen theme.
    The translation credits come from locale/credits.json, which
    tools/make_locale.py writes from the Last-Translator line of each catalogue.
    """
    people = {}
    try:
        with open(os.path.join(_addon_dir(), "locale", "credits.json"), encoding="utf-8") as f:
            people = json.load(f)
    except Exception:
        pass
    code = _cfg_get_str("language_override", "") or _nvda_language()
    language = people.get(code) or people.get(code.split("_")[0]) or {}
    # Older files held a single name; a language can be several people's work.
    names = language.get("translators") or ([language["translator"]]
                                            if language.get("translator") else [])
    theme = _current_theme()
    return {"translators": [name for name in names if name],
            "language": language.get("language", ""),
            "theme": theme["name"] if theme else "",
            "theme_author": theme["author"] if theme else ""}

def _credits_line():
    """One line naming the people whose work the user is reading and hearing."""
    who = _credits()
    parts = [_("SuperTools by {name}").format(name=ADDON_AUTHOR)]
    if who["translators"]:
        parts.append(_("Translation into {language}: {name}").format(
            language=who["language"] or _nvda_language(),
            name=", ".join(who["translators"])))
    if who["theme"] and who["theme_author"]:
        parts.append(_("Sound theme {theme}: {name}").format(
            theme=who["theme"], name=who["theme_author"]))
    return "   •   ".join(parts)

# ── Making a translation from inside the add-on ──────────────────────────────
# A translator should not need Poedit, a checkout and a build to see their own
# language. These write the same .po a translator would send us, and the .mo
# NVDA actually reads, straight into the add-on.

def _pot_texts():
    """Every English text that can be translated, in the order it appears."""
    texts = []
    try:
        path = os.path.join(_addon_dir(), "locale", "nvda.pot")
        current = None
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith('msgid "'):
                current = line[7:-1]
            elif line.startswith('"') and line.endswith('"') and current is not None:
                current += line[1:-1]
            elif line.startswith("msgstr") and current is not None:
                if current:
                    texts.append(current.replace('\\n', "\n").replace('\\"', '"'))
                current = None
    except Exception:
        log.error("SuperTools: could not read the list of texts", exc_info=True)
    return texts

def _po_escape(text):
    return (text.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\n", "\\n").replace("\t", "\\t"))

def _read_po_header(path, field):
    """One header line of a .po file, such as who translated it."""
    marker = '"' + field + ": "
    try:
        for line in open(path, encoding="utf-8"):
            if line.strip().startswith(marker):
                value = line.strip()[len(marker):].rstrip('"')
                while value.endswith("\\n"):
                    value = value[:-2]
                return value.strip()
    except OSError:
        pass
    return ""

def _read_po_file(path):
    """{english: translation} from a .po file the add-on wrote earlier."""
    entries, msgid, msgstr, where = {}, None, None, None
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith('msgid "'):
                if msgid:
                    entries[msgid] = msgstr or ""
                msgid, msgstr, where = line[7:-1], None, "id"
            elif line.startswith('msgstr "'):
                msgstr, where = line[8:-1], "str"
            elif line.startswith('"') and line.endswith('"'):
                chunk = line[1:-1]
                if where == "id":
                    msgid += chunk
                elif where == "str":
                    msgstr = (msgstr or "") + chunk
            elif not line:
                where = None
        if msgid:
            entries[msgid] = msgstr or ""
    except Exception:
        log.debugWarning("SuperTools: could not read {}".format(path), exc_info=True)
    unescape = lambda t: t.replace('\\n', "\n").replace('\\t', "\t").replace('\\"', '"')
    return {unescape(k): unescape(v) for k, v in entries.items() if k}

def _write_po_file(path, code, name, translator, entries, texts):
    """The file a translator sends us, in the shape gettext expects."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write('msgid ""\nmsgstr ""\n'
                '"Project-Id-Version: SuperTools\\n"\n'
                '"MIME-Version: 1.0\\n"\n'
                '"Content-Type: text/plain; charset=UTF-8\\n"\n'
                '"Content-Transfer-Encoding: 8bit\\n"\n'
                '"Language: {}\\n"\n'
                '"Last-Translator: {}\\n"\n'
                '"Language-Team: {}\\n"\n'.format(code, translator, name))
        for text in texts:
            f.write('\nmsgid "{}"\nmsgstr "{}"\n'.format(
                _po_escape(text), _po_escape(entries.get(text, ""))))

def _write_mo_file(path, catalog):
    """Compile a catalogue into the binary form gettext reads."""
    import array
    import struct
    items = sorted((k, v) for k, v in catalog.items() if k and v)
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
    keys, values = [], []
    for id_offset, id_length, str_offset, str_length in offsets:
        keys += [id_length, id_offset + key_start]
        values += [str_length, str_offset + value_start]
    output = struct.pack("Iiiiiii", 0x950412de, 0, len(items),
                         7 * 4, 7 * 4 + len(items) * 8, 0, 0)
    output += array.array("i", keys + values).tobytes()
    output += ids + strs
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(output)

def _user_translation_dir():
    return os.path.join(globalVars.appArgs.configPath, "superToolsTranslations")

def _install_translation(code, catalog):
    """Put a finished translation where NVDA looks for it."""
    path = os.path.join(_addon_dir(), "locale", code, "LC_MESSAGES", "nvda.mo")
    _write_mo_file(path, catalog)
    _catalog_cache.pop(code, None)
    return path

# ── Showing a language before NVDA runs in it ───────────────────────────────
# The add-on follows NVDA's language, which is right for everyone except the
# person writing a translation: they need to see their work now. The override
# is empty unless they ask for it.

_catalog_cache = {}

def _catalog(code):
    if code not in _catalog_cache:
        try:
            import gettext
            _catalog_cache[code] = gettext.translation(
                "nvda", localedir=os.path.join(_addon_dir(), "locale"),
                languages=[code, code.split("_")[0]], fallback=True)
        except Exception:
            _catalog_cache[code] = None
    return _catalog_cache[code]

def _apply_language_override():
    """Speak the add-on in the language the user is translating, if they chose one."""
    global _
    code = _cfg_get_str("language_override", "")
    if not code:
        return False
    catalog = _catalog(code)
    if catalog is None:
        return False
    _ = catalog.gettext
    return True

# ── Config ────────────────────────────────────────────────────────────────────

def _cfg_get_str(key, default=""):
    try:
        v = config.conf[CFG][key]
        return str(v) if v is not None else default
    except KeyError:
        return default

def _cfg_get_bool(key, default=True):
    try:
        v = config.conf[CFG][key]
        if isinstance(v, bool): return v
        return str(v).lower() in ("true","1","yes")
    except KeyError:
        return default

def _cfg_get_int(key, default=0):
    try:
        return int(config.conf[CFG][key])
    except (KeyError, ValueError, TypeError):
        return default

def _cfg_set(key, value):
    if CFG not in config.conf:
        config.conf[CFG] = {}
    config.conf[CFG][key] = value
    config.conf.save()

def _cfg_reset():
    try:
        if CFG in config.conf:
            del config.conf[CFG]
    except Exception:
        log.debugWarning("SuperTools: could not delete config section", exc_info=True)
    _data_reset()
    config.conf.save()

# ── Structured data (JSON file) ───────────────────────────────────────────────
# nvda.ini (configobj) cannot store nested lists / dicts: they are written as
# broken strings and lost after restart, and may even make config saving fail.
# Everything structured (beeps, word categories, command sounds) lives here.

_data_cache = None

def _data_path():
    return os.path.join(globalVars.appArgs.configPath, "superTools.json")

def _data_load():
    global _data_cache
    if _data_cache is not None:
        return _data_cache
    data = {}
    try:
        with open(_data_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except FileNotFoundError:
        data = _data_migrate_legacy()
    except Exception:
        log.error("SuperTools: could not read data file", exc_info=True)
    _data_cache = data
    return data

def _data_save():
    try:
        path = _data_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data_load(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        log.error("SuperTools: could not write data file", exc_info=True)

def _data_get(key, default=None):
    return _data_load().get(key, default)

def _data_set(key, value):
    _data_load()[key] = value
    _data_save()

def _data_reset():
    global _data_cache
    _data_cache = {}
    _forget_word_categories()
    try:
        os.remove(_data_path())
    except OSError:
        pass

def _ask_for_file(parent, title, save=False, default="", wildcard="*.json|*.json"):
    """Ask for one file name; None when the user changes their mind."""
    style = (wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) if save else (wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
    dlg = wx.FileDialog(parent, title, defaultFile=default, wildcard=wildcard, style=style)
    try:
        return dlg.GetPath() if dlg.ShowModal() == wx.ID_OK else None
    finally:
        dlg.Destroy()

def _run_file_task(parent, task, *args):
    """Run something that touches a file and report a failure once, in one place."""
    try:
        return task(*args)
    except Exception as ex:
        log.error("SuperTools: file task failed", exc_info=True)
        gui.messageBox(_("File error: {e}").format(e=ex), "SuperTools", wx.OK | wx.ICON_ERROR, parent)
        return None

def _read_text_file(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()

def _write_text_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True

CONVERT_HISTORY = 20
BACKUP_KEEP = 5

def _backup_dir():
    return os.path.join(globalVars.appArgs.configPath, "superToolsBackups")

def _weekly_backup():
    """
    Keep a copy of the settings once a week, in the background so that starting
    NVDA never waits for it. The oldest copies are cleaned up.
    """
    if not _cfg_get_bool("backup_weekly", True):
        return
    last = _cfg_get_int("backup_last", 0)
    now = int(time.time())
    if now - last < 7 * 24 * 3600:
        return
    _cfg_set("backup_last", now)
    def run():
        try:
            folder = _backup_dir()
            os.makedirs(folder, exist_ok=True)
            _export_settings(os.path.join(folder, "superTools-{}.json".format(
                time.strftime("%Y-%m-%d"))))
            backups = sorted(name for name in os.listdir(folder) if name.endswith(".json"))
            for name in backups[:-BACKUP_KEEP]:
                os.remove(os.path.join(folder, name))
        except Exception:
            log.error("SuperTools: weekly backup failed", exc_info=True)
    threading.Thread(target=run, daemon=True).start()

def _export_settings(path):
    """Write one file holding both the plain settings and the structured data."""
    plain = {}
    try:
        for key in config.conf[CFG]:
            plain[str(key)] = config.conf[CFG][key]
    except KeyError:
        pass
    backup = {"supertools": CURRENT_VERSION, "config": plain, "data": _data_load()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)

def _import_settings(path):
    """Read a file written by _export_settings. False if it is not one."""
    global _data_cache
    with open(path, encoding="utf-8") as f:
        backup = json.load(f)
    if not isinstance(backup, dict) or "supertools" not in backup:
        return False
    plain = backup.get("config")
    if isinstance(plain, dict):
        for key, value in plain.items():
            try:
                _cfg_set(str(key), value)
            except Exception:
                log.debugWarning("SuperTools: could not restore {}".format(key), exc_info=True)
    data = backup.get("data")
    if isinstance(data, dict):
        _data_cache = data
        _data_save()
        _forget_word_categories()
    return True

def _legacy_pairs(raw):
    """Parse old nvda.ini beep values such as ['[440, 200]', '[550, 200]']."""
    result = []
    for item in raw if isinstance(raw, (list, tuple)) else [raw]:
        try:
            if isinstance(item, str):
                item = json.loads(item)
            result.append([int(item[0]), int(item[1])])
        except Exception:
            pass
    return result

def _data_migrate_legacy():
    """Move structured values that older versions put in nvda.ini into the JSON file."""
    data = {}
    try:
        sec = config.conf[CFG]
    except KeyError:
        return data
    try:
        beeps = _legacy_pairs(sec.get("beeps"))
        if beeps:
            data["beeps"] = beeps
    except Exception:
        pass
    try:
        cats = sec.get("word_categories")
        if isinstance(cats, str):
            cats = json.loads(cats)
        if isinstance(cats, list) and cats and all(isinstance(c, dict) for c in cats):
            data["word_categories"] = cats
    except Exception:
        pass
    if "word_categories" not in data:
        try:
            words = sec.get("words", [])
            if isinstance(words, str):
                words = [words]
            words = [str(w).strip() for w in words if str(w).strip()]
            if words:
                data["legacy_words"] = words
        except Exception:
            pass
    # Remove the broken values so they can never break config saving again.
    for key in ("beeps", "word_categories"):
        try:
            if key in sec:
                del sec[key]
        except Exception:
            pass
    return data

# ── Windows API ───────────────────────────────────────────────────────────────

user32 = ctypes.windll.user32

VkKeyScanExW              = user32.VkKeyScanExW
VkKeyScanExW.argtypes     = [wintypes.WCHAR, wintypes.HANDLE]
VkKeyScanExW.restype      = wintypes.SHORT

MapVirtualKeyExW          = user32.MapVirtualKeyExW
MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HANDLE]
MapVirtualKeyExW.restype  = wintypes.UINT

ToUnicodeEx               = user32.ToUnicodeEx
ToUnicodeEx.argtypes      = [
    wintypes.UINT, wintypes.UINT,
    ctypes.POINTER(wintypes.BYTE),
    wintypes.LPWSTR, ctypes.c_int,
    wintypes.UINT, wintypes.HANDLE,
]
ToUnicodeEx.restype       = ctypes.c_int

GetKeyboardLayout             = user32.GetKeyboardLayout
GetKeyboardLayout.argtypes    = [wintypes.DWORD]
GetKeyboardLayout.restype     = wintypes.HANDLE

GetKeyboardLayoutList             = user32.GetKeyboardLayoutList
GetKeyboardLayoutList.argtypes    = [ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
GetKeyboardLayoutList.restype     = ctypes.c_int

GetLocaleInfoW               = ctypes.windll.kernel32.GetLocaleInfoW
LOCALE_SLOCALIZEDDISPLAYNAME = 0x00000002
LOCALE_SLANGUAGE             = 0x00000004
MAPVK_VK_TO_VSC              = 0

# ── Layout helpers ────────────────────────────────────────────────────────────

def _get_installed_layouts():
    count = GetKeyboardLayoutList(0, None)
    arr   = (wintypes.HANDLE * count)()
    GetKeyboardLayoutList(count, arr)
    layouts = []
    seen    = set()
    for hkl in arr:
        lcid = hkl & 0xFFFF
        if lcid in seen: continue
        seen.add(lcid)
        buf = ctypes.create_unicode_buffer(256)
        if GetLocaleInfoW(lcid, LOCALE_SLOCALIZEDDISPLAYNAME, buf, 256) == 0:
            GetLocaleInfoW(lcid, LOCALE_SLANGUAGE, buf, 256)
        name = buf.value or "Layout 0x{:04X}".format(lcid)
        layouts.append((name, "{:04X}".format(lcid), hkl))
    layouts.sort(key=lambda x: x[0])
    return layouts

def _hkl_from_lcid_str(lcid_str):
    try:
        lcid = int(lcid_str, 16)
    except (ValueError, TypeError):
        return None
    count = GetKeyboardLayoutList(0, None)
    arr   = (wintypes.HANDLE * count)()
    GetKeyboardLayoutList(count, arr)
    for hkl in arr:
        if (hkl & 0xFFFF) == lcid:
            return hkl
    return None

def _get_active_hkl():
    hwnd = user32.GetForegroundWindow()
    tid  = user32.GetWindowThreadProcessId(hwnd, None)
    return GetKeyboardLayout(tid)

def _auto_detect_source(text):
    """
    The installed layout that can type most of this text.

    Every character counts, not only the non-ASCII ones: Latin text has to be
    recognised as English even while the keyboard itself is set to Persian,
    otherwise converting English to Persian silently does nothing.
    """
    best_hkl, best_score = None, 0
    for _name, _lcid, hkl in _get_installed_layouts():
        score = _layout_score(text, hkl)
        if score > best_score:
            best_score, best_hkl = score, hkl
    return best_hkl or _get_active_hkl()

def _layout_score(text, hkl):
    """How many characters of the text can be typed on this layout."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0
    return sum(1 for c in chars if VkKeyScanExW(c, hkl) != -1)

def _layout_order():
    """
    The layouts to convert between, in a fixed order.

    Every layout Windows has, unless the user left some out. The order is the
    one Windows reports, so "the next one" means the same thing every time.
    """
    installed = _get_installed_layouts()
    chosen = [code.strip().lower() for code in _cfg_get_str("kb_layouts", "").split(",")
              if code.strip()]
    if chosen:
        picked = [item for item in installed if item[1].lower() in chosen]
        if len(picked) >= 2:
            return picked
    return installed

def _detect_layout(text, layouts):
    """Which of these layouts the text was typed with: the one that can type most of it."""
    best, best_score = None, 0
    for _name, _lcid, hkl in layouts:
        score = _layout_score(text, hkl)
        if score > best_score:
            best, best_score = hkl, score
    return best

def _next_layout(text):
    """
    (source, target, name of the target) for the next step around the ring.

    The source is the layout the text reads as; the target is the one after it.
    With two layouts that is simply the other one, which is what it always did;
    with more, pressing C again carries on to the next.
    """
    layouts = _layout_order()
    if len(layouts) < 2:
        return None, None, ""
    source = _detect_layout(text, layouts) or _get_active_hkl()
    index = next((i for i, (_n, _l, hkl) in enumerate(layouts) if hkl == source), None)
    if index is None:
        # The text belongs to a layout that is not in the ring; start at the top.
        index, source = 0, layouts[0][2]
    target = layouts[(index + 1) % len(layouts)]
    return source, target[2], target[0]

def _other_layout(text, exclude_hkl):
    """
    A layout to convert to when the text is already in the chosen target layout.
    A layout that cannot type this text at all is preferred, because that is the
    one from the other script (Persian for Latin text, English for Persian text).
    """
    layouts = [hkl for _name, _lcid, hkl in _get_installed_layouts() if hkl != exclude_hkl]
    for hkl in layouts:
        if _layout_score(text, hkl) == 0:
            return hkl
    return layouts[0] if layouts else None

def _pick_direction(text, hkl_a, hkl_b):
    """
    Decide which way round to convert between two layouts.

    The text itself says which layout it was typed with: the layout that can
    type most of it is the source, the other one is the target. This is what
    makes the conversion work in both directions without swapping the settings.
    """
    if not hkl_b:
        return hkl_a, hkl_b
    if not hkl_a or hkl_a == hkl_b:
        source = _auto_detect_source(text) or _get_active_hkl()
        if source == hkl_b:
            return source, _other_layout(text, hkl_b) or hkl_b
        return source, hkl_b
    if _layout_score(text, hkl_b) > _layout_score(text, hkl_a):
        return hkl_b, hkl_a
    return hkl_a, hkl_b

def _char_to_layout(char, source_hkl, target_hkl):
    vk_scan = VkKeyScanExW(char, source_hkl)
    if vk_scan == -1: return char
    vk_code     = vk_scan & 0xFF
    shift_state = (vk_scan >> 8) & 0xFF
    scan_code   = MapVirtualKeyExW(vk_code, MAPVK_VK_TO_VSC, target_hkl)
    if scan_code == 0: return char
    key_state = (wintypes.BYTE * 256)()
    if shift_state & 1: key_state[0x10] = 0x80
    buf    = ctypes.create_unicode_buffer(8)
    result = ToUnicodeEx(vk_code, scan_code, key_state, buf, 8, 0, target_hkl)
    return buf.value[0] if result > 0 and buf.value else char

def convert_text(text, src, tgt):
    return "".join(_char_to_layout(c, src, tgt) for c in text)

# ── Beep engine ───────────────────────────────────────────────────────────────
# Stored as "beeps" = [[freq,dur],[freq,dur],...] in config


_media_counter = [0]

def _play_media_file(path):
    """
    Play a sound file Windows knows how to decode (mp3 and friends).
    NVDA's own player only takes wav, so anything else goes through Windows
    Media Control, in a thread of its own so nothing waits for it.
    """
    _media_counter[0] += 1
    alias = "superTools{}".format(_media_counter[0])
    def run():
        send = ctypes.windll.winmm.mciSendStringW
        if send('open "{}" alias {}'.format(path, alias), None, 0, None):
            log.debugWarning("SuperTools: Windows cannot play {}".format(path))
            return
        try:
            send("play {} wait".format(alias), None, 0, None)
        finally:
            send("close {}".format(alias), None, 0, None)
    threading.Thread(target=run, daemon=True).start()
    return True

def _play_sound_file(path):
    """Play a sound file: wav through NVDA itself, everything else through Windows."""
    try:
        if os.path.splitext(path)[1].lower() == ".wav":
            import nvwave
            threading.Thread(target=nvwave.playWaveFile, args=(path,), daemon=True).start()
            return True
        return _play_media_file(path)
    except Exception:
        log.debugWarning("SuperTools: could not play {}".format(path), exc_info=True)
        return False

def _play_event(key, fallback):
    """
    Play one of the add-on's own sounds: what the theme says, or the built-in
    beeps when the theme does not mention this one.
    """
    sound = _theme_sound(key)
    if sound and sound.get("file") and _play_sound_file(sound["file"]):
        return
    if sound and sound.get("beeps"):
        _play_sequence(sound["beeps"], sound.get("gap", 0))
        return
    _play_sequence(fallback)

def _play_alert(settings):
    """
    What a word plays: its own sound file when it has one, then its own beeps.
    A word never loses its settings to a theme; the theme only steps in for
    words left on the built-in default.
    """
    sound = settings.get("sound")
    if sound and os.path.isfile(sound) and _play_sound_file(sound):
        return
    if settings.get("beeps") == [list(b) for b in DEFAULT_WORD_BEEP]:
        theme = _theme_sound("word")
        if theme and theme.get("file") and _play_sound_file(theme["file"]):
            return
        if theme and theme.get("beeps"):
            _play_sequence(theme["beeps"], theme.get("gap", 0), settings["interrupt"])
            return
    _play_sequence(list(settings["beeps"]) * max(1, settings["repeat"]),
                   settings["gap"], settings["interrupt"])

TONE_RATE = getattr(tones, "SAMPLE_RATE", 44100)
if not isinstance(TONE_RATE, int) or TONE_RATE < 8000:
    TONE_RATE = 44100
TONE_FADE = 0.004          # seconds of fade at each end, so a beep cannot click

# How beeps are made. "exact" builds the whole sequence as one piece of sound,
# which is the only way the gaps hold; "nvda" hands each beep to NVDA, which
# sounds exactly like the rest of NVDA but times itself only as well as a
# thread can.
BEEP_ENGINES = ("exact", "nvda")

def _beep_level():
    """How loud the generated beeps are, as the user set it."""
    return max(1, min(100, _cfg_get_int("beep_volume", 35))) / 100.0

def _beep_lead_in():
    """
    Silence at the start of every sequence.
    The audio device needs a moment after being stopped, and without this the
    first beep is cut off or lost altogether.
    """
    return max(0, min(500, _cfg_get_int("beep_lead_in", 60)))

_tone_player = None

def _get_tone_player():
    """One player for all of the add-on's beeps, opened when first needed."""
    global _tone_player
    if _tone_player is None:
        import nvwave
        settings = {"channels": 1, "samplesPerSec": TONE_RATE,
                    "bitsPerSample": 16, "wantDucking": False}
        try:
            import audio
            _tone_player = nvwave.WavePlayer(purpose=audio.AudioPurpose.SOUNDS, **settings)
        except Exception:
            # Older NVDA has no notion of what the audio is for.
            _tone_player = nvwave.WavePlayer(**settings)
    return _tone_player

def _close_tone_player():
    global _tone_player
    player, _tone_player = _tone_player, None
    if player is not None:
        try:
            player.close()
        except Exception:
            pass

def _tone_buffer(beeps, gap):
    """The whole sequence as one piece of sound: tones, and silence between them."""
    import array
    import math
    level = _beep_level()
    samples = array.array("h", [0] * int(TONE_RATE * _beep_lead_in() / 1000.0))
    fade = max(1, int(TONE_RATE * TONE_FADE))
    silence = [0] * int(TONE_RATE * max(0, gap) / 1000.0)
    for index, (frequency, milliseconds) in enumerate(beeps):
        count = max(1, int(TONE_RATE * max(1, milliseconds) / 1000.0))
        step = 2.0 * math.pi * max(1, frequency) / TONE_RATE
        for position in range(count):
            shape = 1.0
            if position < fade:
                shape = position / float(fade)
            elif position > count - fade:
                shape = max(0.0, (count - position) / float(fade))
            samples.append(int(math.sin(step * position) * 32000 * level * shape))
        if silence and index < len(beeps) - 1:
            samples.extend(silence)
    return samples.tobytes()

def _play_sequence(beeps, gap=0, interrupt=False):
    """Play a sequence of beeps in the background, the way the user chose."""
    beeps = [b for b in beeps if b]
    if not beeps:
        return
    def run():
        try:
            if interrupt:
                speech.cancelSpeech()
            if _cfg_get_str("beep_engine", "exact") == "nvda":
                _beep_one_by_one(beeps, gap)
                return
            player = _get_tone_player()
            player.stop()
            player.feed(_tone_buffer(beeps, gap))
        except Exception:
            log.debugWarning("SuperTools: falling back to NVDA's own beep", exc_info=True)
            _close_tone_player()
            _beep_one_by_one(beeps, gap)
    threading.Thread(target=run, daemon=True).start()

def _beep_one_by_one(beeps, gap):
    """
    NVDA's own beep, one tone at a time, waiting out each one.

    This is what the add-on used to do, and it is what a user hears from the
    rest of NVDA. Since tones.beep() stops whatever is playing before it starts,
    the wait has to cover the whole tone, and a little more, or the next beep
    cuts into it. The timing is only as good as a sleeping thread can be, which
    is why it is a choice rather than the default.
    """
    lead = _beep_lead_in()
    if lead:
        try:
            # A tone at no volume: the device wakes up, nobody hears it, and the
            # first real beep is not eaten.
            tones.beep(100, lead, left=0, right=0)
            time.sleep(lead / 1000.0)
        except Exception:
            log.debugWarning("SuperTools: could not wake the sound device", exc_info=True)
    for index, (frequency, milliseconds) in enumerate(beeps):
        started = time.time()
        try:
            tones.beep(int(frequency), int(milliseconds))
        except Exception:
            return
        waited = (time.time() - started) * 1000.0
        delay = milliseconds - waited + max(10, gap if index < len(beeps) - 1 else 0)
        if delay > 0:
            time.sleep(delay / 1000.0)

# ── Sound themes ────────────────────────────────────────────────────────
# A theme gives the add-on's own sounds a different voice. Each sound is either
# a sequence of beeps or a sound file, chosen per sound, and anything the theme
# does not mention keeps the built-in beep. Themes are JSON files, so anyone can
# write one and send it without touching the code.

THEME_NONE = ""

def _theme_dirs():
    return [os.path.join(os.path.dirname(os.path.abspath(__file__)), "superToolsThemes"),
            os.path.join(globalVars.appArgs.configPath, "superToolsThemes")]

def _user_theme_dir():
    return _theme_dirs()[-1]

_themes_cache = None

def _load_themes():
    """{id: theme} for every theme file found, the user's folder winning on a clash."""
    global _themes_cache
    if _themes_cache is not None:
        return _themes_cache
    themes = {}
    for folder in _theme_dirs():
        try:
            filenames = sorted(os.listdir(folder))
        except OSError:
            continue
        for filename in filenames:
            if not filename.lower().endswith(".json"):
                continue
            path = os.path.join(folder, filename)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                sounds = data.get("sounds")
                if not isinstance(sounds, dict):
                    continue
                theme_id = os.path.splitext(filename)[0].lower()
                themes[theme_id] = {
                    "id": theme_id,
                    "name": str(data.get("name") or theme_id),
                    "author": str(data.get("author") or ""),
                    "description": str(data.get("description") or ""),
                    "folder": folder,
                    "sounds": sounds,
                }
            except Exception:
                log.error("SuperTools: unusable theme {}".format(filename), exc_info=True)
    _themes_cache = themes
    return themes

def _forget_themes():
    global _themes_cache
    _themes_cache = None

def _theme_items():
    """[(id, label)] for the settings, the built-in beeps first."""
    items = [(THEME_NONE, _("Built-in beeps"))]
    for theme in sorted(_load_themes().values(), key=lambda t: t["name"].lower()):
        label = theme["name"]
        if theme["author"]:
            label += " — " + _("by {author}").format(author=theme["author"])
        items.append((theme["id"], label))
    return items

def _current_theme():
    return _load_themes().get(_cfg_get_str("sound_theme", THEME_NONE))

def _theme_sound(key):
    """
    What the current theme says this sound is: a file path, a beep sequence, or
    None when the theme is silent about it and the built-in beep should play.
    """
    theme = _current_theme()
    if not theme:
        return None
    entry = theme["sounds"].get(key)
    if isinstance(entry, str):
        entry = {"file": entry}
    if not isinstance(entry, dict):
        return None
    name = entry.get("file")
    if name:
        path = name if os.path.isabs(name) else os.path.join(theme["folder"], name)
        if os.path.isfile(path):
            return {"file": path}
        log.debugWarning("SuperTools: theme file missing: {}".format(path))
    beeps = entry.get("beeps")
    if beeps:
        return {"beeps": _normalize_beeps(beeps), "gap": int(entry.get("gap", 30) or 0)}
    return None

def _write_theme_template(path, keys):
    """A starting point a theme author can fill in: every sound, with the built-in beeps."""
    data = {
        "name": "My theme",
        "author": "Your name",
        "description": "What this theme sounds like",
        "_help": ("Each sound is either a file next to this one "
                  "(\"file\": \"start.wav\") or beeps "
                  "(\"beeps\": [[frequency, milliseconds], ...]). "
                  "Remove what you do not want to change: anything missing keeps "
                  "the built-in beep. wav plays through NVDA's own audio; mp3 and "
                  "other formats play through Windows."),
        "sounds": {key: {"beeps": [list(b) for b in beeps]} for key, beeps in keys.items()},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)

# ── Command mode sounds ───────────────────────────────────────────────────────
# Every command gets its own beep sequence so the user can tell by ear which
# command ran. Sequences are stored in the data file under "command_sounds".

COMMAND_SOUND_DEFAULTS = {
    "start":   [[523, 60], [784, 60]],
    "h":       [[880, 70]],
    "x":       [[988, 70]],
    "c":       [[659, 70]],
    "s":       [[740, 70]],
    "w":       [[1047, 70]],
    "shift+c": [[659, 70], [880, 70]],
    "shift+w": [[440, 60], [880, 60]],
    "p":       [[1175, 70]],
    "l":       [[880, 70], [440, 120]],
    "t":       [[698, 60], [932, 60], [1175, 60]],
    "u":       [[784, 60], [1047, 70]],
    "locked":  [[150, 90]],
    "escape":  [[392, 70], [262, 90]],
    "z":       [[523, 60], [392, 80]],
    "unknown": [[200, 120]],
    "autocheck": [[300, 45], [240, 60]],
}

# (key, label) in the order shown in the settings dialog.
COMMAND_SOUND_ITEMS = [
    ("start",   "Command mode started"),
    ("h",       "H - Help"),
    ("x",       "X - Changes"),
    ("c",       "C - Layout conversion"),
    ("shift+c", "Shift+C - Convert the word before the cursor"),
    ("z",       "Z - Undo the last conversion"),
    ("s",       "S - Settings"),
    ("w",       "W - Word Monitor manager"),
    ("shift+w", "Shift+W - Toggle Word Monitor"),
    ("p",       "P - Process Manager"),
    ("l",       "L - Lock or unlock the keyboard"),
    ("t",       "T - Clock"),
    ("u",       "U - Look for a new version"),
    ("escape",  "Escape - Cancel"),
    ("unknown", "Unknown command"),
    ("locked",  "A key pressed while the keyboard is locked"),
]

def _get_command_sounds():
    sounds = {k: [list(b) for b in v] for k, v in COMMAND_SOUND_DEFAULTS.items()}
    stored = _data_get("command_sounds")
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key in sounds:
                sounds[key] = _normalize_beeps(value, sounds[key])
    return sounds

def _get_command_sound(key):
    return _get_command_sounds().get(key, COMMAND_SOUND_DEFAULTS["unknown"])

def _set_command_sounds(sounds):
    _data_set("command_sounds", {k: [[int(f), int(d)] for f, d in v]
                                 for k, v in sounds.items() if k in COMMAND_SOUND_DEFAULTS})

# ── Application rules ───────────────────────────────────────────────
# A feature can be limited to some applications, or kept out of them. The rule
# is read from a set built once per change, and the application name comes from
# NVDA's own app module, so this stays cheap enough for the speech path.

APP_MODES = ("all", "only", "except")

_app_rules_cache = {}

def _app_rule(feature):
    """(mode, {application names}) for a feature."""
    rule = _app_rules_cache.get(feature)
    if rule is None:
        mode = _cfg_get_str(feature + "_app_mode", "all")
        if mode not in APP_MODES:
            mode = "all"
        names = {name.strip().lower().replace(".exe", "")
                 for name in _cfg_get_str(feature + "_apps", "").split(",")
                 if name.strip()}
        rule = (mode, names)
        _app_rules_cache[feature] = rule
    return rule

def _forget_app_rules():
    _app_rules_cache.clear()

def _current_app():
    """The application in focus, as a plain name such as "notepad"."""
    try:
        focus = api.getFocusObject()
        name = getattr(getattr(focus, "appModule", None), "appName", "") or ""
    except Exception:
        name = ""
    return name.lower().replace(".exe", "")

def _feature_allowed_here(feature):
    """Does this feature apply to the application in focus?"""
    mode, names = _app_rule(feature)
    if mode == "all" or not names:
        return True
    return (_current_app() in names) if mode == "only" else (_current_app() not in names)

# ── The clock ──────────────────────────────────────────────────────────

# Any web server tells you the time in the Date header of its answer, so no
# service has to be signed up for and nothing about the user is sent. The plain
# http addresses are the second try on purpose: when the clock is badly wrong,
# https itself stops working, which is exactly the case we want to repair. They
# are read for one header and nothing else.
CLOCK_HOSTS = ("https://api.github.com/", "https://www.cloudflare.com/",
               "http://www.msftconnecttest.com/connecttest.txt",
               "http://neverssl.com/")
CLOCK_TIMEOUT = 10
CLOCK_TOLERANCE = 5          # seconds; below this nobody would notice

def _server_time():
    """(seconds since the epoch, as a web server sees it; which server answered)."""
    import email.utils
    import urllib.request
    last = None
    for host in CLOCK_HOSTS:
        try:
            request = urllib.request.Request(host, method="HEAD", headers={
                "User-Agent": "SuperTools/{} (NVDA add-on)".format(CURRENT_VERSION)})
            with urllib.request.urlopen(request, timeout=CLOCK_TIMEOUT) as response:
                stamp = response.headers.get("Date")
            parsed = email.utils.parsedate_tz(stamp) if stamp else None
            if parsed:
                return email.utils.mktime_tz(parsed), host
        except Exception as ex:
            last = ex
            log.debugWarning("SuperTools: no time from " + host, exc_info=True)
    raise last if last is not None else OSError("no server answered")

def _clock_drift():
    """(how many seconds the computer is ahead, which server said so)."""
    server, host = _server_time()
    return time.time() - server, host

def _drift_sentence(drift, host):
    """The difference, in words, for someone who is listening rather than reading."""
    if abs(drift) < CLOCK_TOLERANCE:
        return _("The clock is right, according to {host}.").format(host=host)
    seconds = abs(int(round(drift)))
    if seconds < 120:
        amount = _("{n} seconds").format(n=seconds)
    elif seconds < 7200:
        amount = _("{n} minutes").format(n=int(round(seconds / 60.0)))
    elif seconds < 172800:
        amount = _("{n} hours").format(n=int(round(seconds / 3600.0)))
    else:
        amount = _("{n} days").format(n=int(round(seconds / 86400.0)))
    return (_("The clock is {amount} ahead of {host}.")
            if drift > 0 else
            _("The clock is {amount} behind {host}.")).format(amount=amount, host=host)

def _run_admin_script(commands, timeout=180):
    """
    Run a few commands as Administrator and give back what they printed.

    Windows shows its own permission prompt. If the user says no, nothing runs
    and that is not an error, only an answer. The commands go into a file so
    that no quoting of ours can turn into a command of someone else's.
    """
    folder = os.path.join(tempfile.gettempdir(), "superTools")
    os.makedirs(folder, exist_ok=True)
    script = os.path.join(folder, "clock.cmd")
    output = os.path.join(folder, "clock.log")
    for path in (output,):
        try:
            os.remove(path)
        except OSError:
            pass
    with open(script, "w", encoding="mbcs", errors="replace") as f:
        f.write("@echo off\r\n")
        for command in commands:
            f.write('{} >> "{}" 2>&1\r\n'.format(command, output))

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NO_CONSOLE = 0x00008000
    ERROR_CANCELLED = 1223
    SW_HIDE = 0

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    info.lpVerb = "runas"
    info.lpFile = script
    info.nShow = SW_HIDE
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == ERROR_CANCELLED:
            return False, _("Permission was not given, so the clock was left alone.")
        return False, _("Windows would not run the command ({code}).").format(code=code)
    kernel = ctypes.windll.kernel32
    if info.hProcess:
        kernel.WaitForSingleObject(info.hProcess, int(timeout * 1000))
        kernel.CloseHandle(info.hProcess)
    try:
        with open(output, encoding="mbcs", errors="replace") as f:
            return True, f.read().strip()
    except OSError:
        return True, ""

def _sync_clock_with_windows():
    """Ask the Windows time service to do what it is for."""
    return _run_admin_script([
        "sc config w32time start= auto",
        "net start w32time",
        "w32tm /resync /force",
    ])

def _set_clock(server_seconds):
    """
    Set the clock to a time we read from a web server.

    This is the second choice, for when the Windows time service cannot reach
    its own servers - behind some networks it cannot. The time is passed as
    plain digits and read back as universal time, so no country's way of
    writing a date can change what it means.
    """
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime(server_seconds))
    powershell = (
        "powershell -NoProfile -Command \"Set-Date ([datetime]::ParseExact('{}',"
        "'yyyyMMddHHmmss',$null,[System.Globalization.DateTimeStyles]::AssumeUniversal "
        "-bor [System.Globalization.DateTimeStyles]::AdjustToUniversal).ToLocalTime())\""
    ).format(stamp)
    return _run_admin_script([powershell])

# ── Looking for a new version ──────────────────────────────────────────

UPDATE_URL = "https://api.github.com/repos/AbolfazlAbaspoor/nvda-supertools/releases/latest"
UPDATE_INTERVAL = 24 * 3600      # at most once a day when it runs by itself
UPDATE_TIMEOUT = 25              # seconds; a tunnelled connection can be slow to start
UPDATE_START_DELAY = 90          # seconds after NVDA starts, so startup stays quick

NO_RELEASE = "no-release"

def _latest_release():
    """
    {version, name, notes, page} for the newest release.

    NO_RELEASE means the question was answered but there is nothing published to
    compare with, which is what a repository with no releases says, and what a
    private one says to anybody who is not signed in. Nothing but a read: no
    download, no identifier, nothing sent about the user.
    """
    import urllib.error
    import urllib.request
    request = urllib.request.Request(UPDATE_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "SuperTools/{} (NVDA add-on)".format(CURRENT_VERSION),
    })
    try:
        with urllib.request.urlopen(request, timeout=UPDATE_TIMEOUT) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return NO_RELEASE
        raise
    except Exception:
        # One retry: the first attempt often fails while a tunnel or a proxy
        # wakes up, and the second one goes through.
        log.debugWarning("SuperTools: first attempt failed, trying once more", exc_info=True)
        with urllib.request.urlopen(request, timeout=UPDATE_TIMEOUT) as response:
            release = json.loads(response.read().decode("utf-8"))
    version = str(release.get("tag_name") or "").lstrip("vV")
    if not version:
        return NO_RELEASE
    download = ""
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if name.lower().endswith(".nvda-addon"):
            download = str(asset.get("browser_download_url") or "")
            break
    return {"version": version,
            "name": str(release.get("name") or version),
            "notes": str(release.get("body") or "").strip(),
            "page": str(release.get("html_url") or ""),
            "download": download}

def _download_release(release, on_done):
    """
    Fetch the add-on file in the background. on_done(path, error) runs on the
    GUI thread; path is a file in the temporary folder, and nothing is
    installed by it. NVDA does the installing, and asks first.
    """
    import urllib.request
    def run():
        try:
            request = urllib.request.Request(release["download"], headers={
                "User-Agent": "SuperTools/{} (NVDA add-on)".format(CURRENT_VERSION)})
            with urllib.request.urlopen(request, timeout=UPDATE_TIMEOUT) as response:
                data = response.read()
            folder = os.path.join(tempfile.gettempdir(), "superTools")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "SuperTools-{}.nvda-addon".format(release["version"]))
            with open(path, "wb") as f:
                f.write(data)
            wx.CallAfter(on_done, path, None)
        except Exception as ex:
            log.debugWarning("SuperTools: could not download the new version", exc_info=True)
            wx.CallAfter(on_done, None, ex)
    threading.Thread(target=run, daemon=True).start()

def _install_addon(path):
    """
    Give the file to NVDA. NVDA shows its own question and its own restart
    prompt, so the user reads the same words they would see for any add-on and
    nothing is installed behind their back.
    """
    try:
        from gui import addonGui
        wx.CallAfter(addonGui.installAddon, gui.mainFrame, path)
        return True
    except Exception:
        log.debugWarning("SuperTools: NVDA has no installAddon here", exc_info=True)
    try:
        os.startfile(path)
        return True
    except Exception:
        log.error("SuperTools: could not open the downloaded file", exc_info=True)
        return False

def _update_available(release):
    return (isinstance(release, dict)
            and _version_tuple(release["version"]) > _version_tuple(CURRENT_VERSION))

def _check_for_update(on_result, force=False):
    """
    Ask about a new version in the background; never hold NVDA up for it.
    on_result(release, error) is called on the GUI thread, release being None
    when there is nothing newer.
    """
    if not force:
        if not _cfg_get_bool("update_check", False):
            return
        if int(time.time()) - _cfg_get_int("update_last", 0) < UPDATE_INTERVAL:
            return
    def run():
        try:
            release = _latest_release()
            _cfg_set("update_last", int(time.time()))
            if release == NO_RELEASE:
                wx.CallAfter(on_result, NO_RELEASE, None)
            else:
                newer = _update_available(release)
                # A version the user chose to skip is not brought up again by
                # itself; asking for it by hand still shows it.
                if newer and not force and release["version"] == _cfg_get_str("update_skip", ""):
                    newer = False
                wx.CallAfter(on_result, release if newer else None, None)
        except Exception as ex:
            log.debugWarning("SuperTools: could not check for a new version", exc_info=True)
            wx.CallAfter(on_result, None, ex)
    threading.Thread(target=run, daemon=True).start()

def _network_error(error):
    """
    What to tell the user about a failed attempt.

    The exceptions that come out of a socket are unreadable, and none of them
    mean anything the user can act on beyond "it did not get through", so they
    all become the same sentence and the detail goes to the log.
    """
    import urllib.error
    if isinstance(error, urllib.error.HTTPError):
        return _("GitHub answered {code}. Try again later.").format(code=error.code)
    return _("Could not reach the internet. Check your connection, and if you use a VPN "
             "or a proxy, that it is working, then try again.")

def _open_page(url):
    try:
        os.startfile(url)
        return True
    except Exception:
        log.debugWarning("SuperTools: could not open {}".format(url), exc_info=True)
        return False

# ── Word monitor ────────────────────────────────────────────────
# A category holds words and the settings new words in it start from.
# A word either carries its own settings or inherits the ones of its category.

DEFAULT_WORD_BEEP = [[880, 90], [1320, 110]]

# Everything that can be set per word (and per category, as the default).
WORD_SETTING_KEYS = ("prefix", "beeps", "gap", "repeat", "interrupt",
                     "match", "case", "action", "sound")
MATCH_MODES  = ("part", "word")
WORD_ACTIONS = ("beep", "speak", "both", "mute")

def _default_word_settings():
    return {"prefix": "", "beeps": [list(b) for b in DEFAULT_WORD_BEEP], "gap": 30,
            "repeat": 1, "interrupt": False, "match": "part", "case": False,
            "action": "beep", "sound": ""}

DEFAULT_WORD_CATEGORIES = [
    {"name": "Lovely ones words", "beeps": DEFAULT_WORD_BEEP, "action": "beep"},
    {"name": "Block list", "beeps": [[220, 120], [180, 160]], "action": "mute"},
    {"name": "Important words", "beeps": [[660, 80], [990, 80]], "action": "both",
     "prefix": "important"},
]

def _normalize_beeps(value, fallback=None):
    fallback = fallback or DEFAULT_WORD_BEEP
    try:
        if isinstance(value, list) and value:
            result = []
            for item in value:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    result.append([max(1, int(item[0])), max(1, int(item[1]))])
            if result:
                return result
    except Exception:
        pass
    return [list(x) for x in fallback]

def _parse_beep_text(text, fallback=None):
    """Parse "440,120; 880,90" into [[440,120],[880,90]]."""
    beeps = []
    for part in str(text).split(";"):
        part = part.strip()
        if not part:
            continue
        try:
            freq, _, dur = part.partition(",")
            beeps.append([max(1, int(freq.strip())), max(1, int(dur.strip()))])
        except (ValueError, TypeError):
            pass
    return beeps or [list(b) for b in (fallback or [[440, 120]])]

def _format_beep_text(beeps):
    return "; ".join("{},{}".format(f, d) for f, d in (beeps or []))

def _build_beeps(count, frequency, duration, step=0):
    """The simple way to describe a sequence: how many beeps, how high, how long."""
    count = max(1, int(count))
    return [[max(1, int(frequency) + int(step) * i), max(1, int(duration))]
            for i in range(count)]

def _normalize_word_settings(raw, fallback=None):
    """Clean one settings block, falling back to the category's or the built-in one."""
    base = dict(fallback or _default_word_settings())
    if not isinstance(raw, dict):
        return base
    result = dict(base)
    if raw.get("beeps"):
        result["beeps"] = _normalize_beeps(raw.get("beeps"), base["beeps"])
    if "prefix" in raw:
        result["prefix"] = str(raw.get("prefix") or "")
    if "sound" in raw:
        result["sound"] = str(raw.get("sound") or "")
    for key, low, high in (("gap", 0, 5000), ("repeat", 1, 20)):
        try:
            if raw.get(key) is not None:
                result[key] = min(high, max(low, int(raw.get(key))))
        except (TypeError, ValueError):
            pass
    if "interrupt" in raw:
        result["interrupt"] = bool(raw.get("interrupt"))
    if "case" in raw:
        result["case"] = bool(raw.get("case"))
    if str(raw.get("match", "")).lower() in MATCH_MODES:
        result["match"] = str(raw.get("match")).lower()
    if str(raw.get("action", "")).lower() in WORD_ACTIONS:
        result["action"] = str(raw.get("action")).lower()
    return result

def _default_word_categories():
    categories = []
    for item in DEFAULT_WORD_CATEGORIES:
        settings = _normalize_word_settings(item)
        settings["name"] = item["name"]
        settings["enabled"] = True
        settings["words"] = []
        categories.append(settings)
    return categories

def _normalize_word_categories(raw):
    if not isinstance(raw, list):
        return _default_word_categories()
    result = []
    for cat in raw:
        if not isinstance(cat, dict):
            continue
        settings = _normalize_word_settings(cat)
        settings["name"] = str(cat.get("name") or "Custom")
        settings["enabled"] = bool(cat.get("enabled", True))
        words = []
        for item in cat.get("words", []):
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            # "inherit" keeps a word following its category; older files stored
            # a word with no beeps of its own, which meant the same thing.
            inherit = bool(item.get("inherit", not item.get("beeps")))
            word = {"text": text, "enabled": bool(item.get("enabled", True)),
                    "inherit": inherit}
            word.update(_normalize_word_settings(item, settings))
            words.append(word)
        settings["words"] = words
        result.append(settings)
    return result or _default_word_categories()

def _word_settings(category, word):
    """The settings a word really uses, after inheritance."""
    if word.get("inherit", True):
        return _normalize_word_settings(category)
    return _normalize_word_settings(word, category)

_categories_cache = None
_matchers_cache = None

# How often each word has been heard. Counting happens while NVDA speaks, so it
# only touches memory; the file is written when the dialog or NVDA closes.
_word_counts = None
_counts_dirty = False

def _get_word_counts():
    global _word_counts
    if _word_counts is None:
        stored = _data_get("word_counts")
        _word_counts = {str(k): int(v) for k, v in stored.items()} if isinstance(stored, dict) else {}
    return _word_counts

def _count_word(word):
    global _counts_dirty
    counts = _get_word_counts()
    counts[word] = counts.get(word, 0) + 1
    _counts_dirty = True

def _save_word_counts():
    global _counts_dirty
    if _counts_dirty and _word_counts is not None:
        _data_set("word_counts", _word_counts)
        _counts_dirty = False

def _get_word_categories():
    """The word categories, prepared once and kept until they change."""
    global _categories_cache
    if _categories_cache is not None:
        return _categories_cache
    try:
        raw = _data_get("word_categories")
        if raw is None:
            cats = _default_word_categories()
            legacy = _data_get("legacy_words") or []
            if legacy:
                cats[0]["words"] = [{"text": str(x), "enabled": True, "inherit": True}
                                    for x in legacy if str(x).strip()]
            _set_word_categories(cats)
            return _categories_cache
        _categories_cache = _normalize_word_categories(raw)
    except Exception:
        log.error("SuperTools: could not read word categories", exc_info=True)
        _categories_cache = _default_word_categories()
    return _categories_cache

def _set_word_categories(categories):
    global _categories_cache, _matchers_cache
    _categories_cache = _normalize_word_categories(categories)
    _matchers_cache = None
    _data_set("word_categories", _categories_cache)

def _forget_word_categories():
    """Called when the data file is replaced under us (settings import, reset)."""
    global _categories_cache, _matchers_cache
    _categories_cache = None
    _matchers_cache = None

def _get_monitor_enabled():
    return _cfg_get_bool("monitor_enabled", True)

def _set_monitor_enabled(val):
    _cfg_set("monitor_enabled", bool(val))

def _word_matchers():
    """
    [(word, settings, compiled pattern)] for every enabled word.

    This is what runs against every phrase NVDA speaks, so it is built once and
    reused: no re-reading, no re-validating and no recompiling per phrase.
    """
    global _matchers_cache
    if _matchers_cache is not None:
        return _matchers_cache
    matchers = []
    for category in _get_word_categories():
        if not category.get("enabled", True):
            continue
        for word in category["words"]:
            if not word.get("enabled", True) or not word["text"]:
                continue
            settings = _word_settings(category, word)
            flags = 0 if settings["case"] else re.IGNORECASE
            pattern = re.escape(word["text"])
            if settings["match"] == "word":
                pattern = r"(?<!\w){}(?!\w)".format(pattern)
            try:
                matchers.append((word["text"], settings, re.compile(pattern, flags)))
            except re.error:
                log.debugWarning("SuperTools: unusable word {}".format(word["text"]), exc_info=True)
    _matchers_cache = matchers
    return matchers

def _find_word_matches(text):
    """[(word, settings)] for every enabled word found in the spoken text."""
    return [(word, settings) for word, settings, pattern in _word_matchers()
            if pattern.search(text)]

def _mute_word(text, word, settings):
    """Remove a word from what is about to be spoken."""
    for candidate, _settings, pattern in _word_matchers():
        if candidate == word:
            return pattern.sub(" ", text)
    return text

# ── Process Manager ───────────────────────────────────────────────────────────
def _get_psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None

# ── Reading the process list from Windows ─────────────────────────────────

SYSTEM_PROCESS_INFORMATION_CLASS = 5
STATUS_INFO_LENGTH_MISMATCH      = 0xC0000004
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p)]

class _SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
    """Only the head of the structure is described: that is all we read."""
    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG),
        ("NumberOfThreads", wintypes.ULONG),
        ("WorkingSetPrivateSize", ctypes.c_longlong),
        ("HardFaultCount", wintypes.ULONG),
        ("NumberOfThreadsHighWatermark", wintypes.ULONG),
        ("CycleTime", ctypes.c_ulonglong),
        ("CreateTime", ctypes.c_longlong),
        ("UserTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),
        ("ImageName", _UNICODE_STRING),
        ("BasePriority", ctypes.c_long),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", wintypes.ULONG),
        ("SessionId", wintypes.ULONG),
        ("UniqueProcessKey", ctypes.c_size_t),
        ("PeakVirtualSize", ctypes.c_size_t),
        ("VirtualSize", ctypes.c_size_t),
        ("PageFaultCount", wintypes.ULONG),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
    ]

def _system_processes():
    """
    [(pid, name, memory, cpu time in 100ns)] for every process, in one call.
    Empty when the call is not available, so the caller can fall back.
    """
    try:
        query = ctypes.windll.ntdll.NtQuerySystemInformation
        size = 512 * 1024
        for _attempt in range(6):
            buffer = ctypes.create_string_buffer(size)
            needed = wintypes.ULONG(0)
            status = query(SYSTEM_PROCESS_INFORMATION_CLASS, buffer, size, ctypes.byref(needed))
            if status == 0:
                break
            if status & 0xFFFFFFFF != STATUS_INFO_LENGTH_MISMATCH:
                return []
            size = max(needed.value + 64 * 1024, size * 2)
        else:
            return []
        processes = []
        offset = 0
        while True:
            entry = _SYSTEM_PROCESS_INFORMATION.from_buffer(buffer, offset)
            name = ""
            if entry.ImageName.Buffer and entry.ImageName.Length:
                name = ctypes.wstring_at(entry.ImageName.Buffer, entry.ImageName.Length // 2)
            pid = entry.UniqueProcessId or 0
            if pid:
                processes.append((int(pid), name or "System",
                                  int(entry.WorkingSetSize),
                                  int(entry.UserTime) + int(entry.KernelTime)))
            if not entry.NextEntryOffset:
                break
            offset += entry.NextEntryOffset
        return processes
    except Exception:
        log.debugWarning("SuperTools: native process list unavailable", exc_info=True)
        return []

_cpu_previous = {}
_cpu_previous_time = 0.0

def _cpu_percentages(processes):
    """
    {pid: percent} worked out from how much processor time each process used
    since the last look. The first look has nothing to compare with and gives
    zero, exactly like every task manager.
    """
    global _cpu_previous, _cpu_previous_time
    now = time.time()
    elapsed = now - _cpu_previous_time
    previous, _cpu_previous, _cpu_previous_time = _cpu_previous, {}, now
    percentages = {}
    cores = max(1, os.cpu_count() or 1)
    for pid, _name, _memory, ticks in processes:
        _cpu_previous[pid] = ticks
        if previous and 0 < elapsed < 3600 and pid in previous:
            used = (ticks - previous[pid]) / 1e7          # 100ns units to seconds
            percentages[pid] = max(0.0, min(100.0, used / elapsed * 100.0 / cores))
    return percentages

_process_path_cache = {}

def _process_path(pid):
    """The program a process runs, kept per process id."""
    if pid in _process_path_cache:
        return _process_path_cache[pid]
    path = ""
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)):
                path = buffer.value
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    _process_path_cache[pid] = path
    return path

_publisher_cache = {}

def _publisher(path):
    """
    Who signed or published a program, read from the file itself.
    The answer is kept, because reading version information is slow and the
    file behind a given path does not change while Windows is running.
    """
    if not path:
        return ""
    if path in _publisher_cache:
        return _publisher_cache[path]
    company = ""
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if size:
            buffer = ctypes.create_string_buffer(size)
            ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buffer)
            value = ctypes.c_void_p()
            length = wintypes.UINT()
            if ctypes.windll.version.VerQueryValueW(
                    buffer, "\\VarFileInfo\\Translation",
                    ctypes.byref(value), ctypes.byref(length)) and length.value >= 4:
                codes = ctypes.cast(value, ctypes.POINTER(wintypes.WORD))
                query = "\\StringFileInfo\\{:04x}{:04x}\\CompanyName".format(codes[0], codes[1])
                if ctypes.windll.version.VerQueryValueW(
                        buffer, query, ctypes.byref(value), ctypes.byref(length)) and length.value:
                    company = ctypes.wstring_at(value, length.value - 1)
    except Exception:
        log.debugWarning("SuperTools: no publisher for {}".format(path), exc_info=True)
    _publisher_cache[path] = company
    return company

def _get_process_rows(with_cpu=False):
    """
    [(pid, name, memory, cpu, publisher)] for every process.

    Windows answers in one call; psutil and tasklist are only used if that ever
    fails. Processor use and the publisher are worked out only when asked for,
    because the publisher has to be read out of each program file once.
    """
    processes = _system_processes()
    if processes:
        percentages = _cpu_percentages(processes) if with_cpu else {}
        rows = []
        for pid, name, memory, _ticks in processes:
            publisher = _publisher(_process_path(pid)) if with_cpu else ""
            rows.append((pid, name, memory, percentages.get(pid, 0.0), publisher))
        return _sort_process_rows(rows)
    return _sort_process_rows(_fallback_process_rows(with_cpu))

def _fallback_process_rows(with_cpu=False):
    """Used only if Windows would not give us the list: psutil, then tasklist."""
    procs = []
    psutil = _get_psutil()
    if psutil:
        fields = ["pid", "name", "memory_info"] + (["cpu_percent", "exe"] if with_cpu else [])
        try:
            for p in psutil.process_iter(fields):
                try:
                    memory = getattr(p.info.get("memory_info"), "rss", 0) or 0
                    cpu = float(p.info.get("cpu_percent") or 0.0) if with_cpu else 0.0
                    publisher = _publisher(p.info.get("exe")) if with_cpu else ""
                    procs.append((int(p.info["pid"]), p.info["name"] or "",
                                  int(memory), cpu, publisher))
                except Exception:
                    pass
        except Exception:
            log.debugWarning("SuperTools: process list failed", exc_info=True)
    if not procs:
        try:
            out = subprocess.check_output(["tasklist", "/fo", "csv", "/nh"], creationflags=0x08000000)
            for line in out.decode("utf-8", errors="replace").splitlines():
                parts = line.strip().split('","')
                if len(parts) >= 2:
                    name = parts[0].lstrip('"')
                    try:
                        procs.append((int(parts[1].strip('"')), name, 0, 0.0, ""))
                    except ValueError:
                        pass
        except Exception:
            log.debugWarning("SuperTools: tasklist failed", exc_info=True)
    return procs

PM_SORT_KEYS     = ("name", "memory", "cpu", "pid")
PM_PRIORITY_KEYS = ("idle", "below", "normal", "above", "high")

def _restart_one(pid):
    """Restart one process; True when it came back."""
    started, _name, _error = _restart_process(pid)
    return started

def _sort_process_rows(rows, order=None):
    """Sort the rows the way the settings ask for."""
    order = order or _cfg_get_str("pm_sort", "name")
    if order == "memory":
        return sorted(rows, key=lambda row: row[2], reverse=True)
    if order == "cpu":
        return sorted(rows, key=lambda row: row[3], reverse=True)
    if order == "pid":
        return sorted(rows, key=lambda row: row[0])
    return sorted(rows, key=lambda row: row[1].lower())

def _filter_process_rows(rows, text):
    """Filter by name, or by PID when a number is typed."""
    text = str(text).strip()
    if not text:
        return list(rows)
    if text.isdigit():
        return [row for row in rows if str(row[0]).startswith(text)]
    folded = text.casefold()
    return [row for row in rows if folded in row[1].casefold()]

PRIORITY_CLASSES = {"idle": 0x0040, "below": 0x4000, "normal": 0x0020,
                    "above": 0x8000, "high": 0x0080}
PROCESS_SET_INFORMATION = 0x0200

def _process_info(pid):
    """Name, program, memory and state of one process."""
    pid = int(pid)
    for other, name, memory, _ticks in _system_processes():
        if other == pid:
            return {"pid": pid, "name": name, "exe": _process_path(pid),
                    "memory": memory, "status": _("running")}
    psutil = _get_psutil()
    if psutil:
        try:
            process = psutil.Process(pid)
            return {"pid": pid, "name": process.name(), "exe": process.exe(),
                    "memory": process.memory_info().rss, "status": process.status()}
        except Exception:
            pass
    return {"pid": pid, "name": "", "exe": None, "memory": 0, "status": "?"}

def _set_process_priority(pid, priority):
    """Change how much processor time a process may take."""
    value = PRIORITY_CLASSES.get(priority)
    if value is None:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, int(pid))
    if handle:
        try:
            return bool(ctypes.windll.kernel32.SetPriorityClass(handle, value))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    psutil = _get_psutil()
    if psutil:
        try:
            names = {"idle": psutil.IDLE_PRIORITY_CLASS, "below": psutil.BELOW_NORMAL_PRIORITY_CLASS,
                     "normal": psutil.NORMAL_PRIORITY_CLASS, "above": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
                     "high": psutil.HIGH_PRIORITY_CLASS}
            psutil.Process(int(pid)).nice(names[priority])
            return True
        except Exception:
            log.debugWarning("SuperTools: priority refused", exc_info=True)
    return False

def _forget_process(pid):
    _process_path_cache.pop(int(pid), None)
    _cpu_previous.pop(int(pid), None)

def _kill_process(pid):
    psutil = _get_psutil()
    try:
        _forget_process(pid)
        if psutil:
            psutil.Process(int(pid)).terminate()
            return True
        subprocess.run(["taskkill", "/f", "/pid", str(int(pid))], creationflags=0x08000000,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True
    except Exception:
        return False

# Flags that cut every tie between the new process and NVDA: no shared console,
# its own process group, and out of the job object NVDA may live in. Without
# CREATE_BREAKAWAY_FROM_JOB a restarted program can be killed together with NVDA.
DETACHED_PROCESS          = 0x00000008
CREATE_NEW_PROCESS_GROUP  = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

def _launch_detached(command, cwd=None):
    """
    Start a program so that it keeps running independently of NVDA: it is not a
    child that NVDA's exit or restart can take down, and it inherits no handles.
    """
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    # A job object may forbid breakaway; then try again without that flag.
    for creationflags in (flags, flags & ~CREATE_BREAKAWAY_FROM_JOB):
        try:
            subprocess.Popen(command, shell=False, close_fds=True,
                             creationflags=creationflags, cwd=cwd,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except Exception:
            log.debugWarning("SuperTools: detached launch failed for {}".format(command),
                             exc_info=True)
    return False

def _restart_process(pid):
    info = _process_info(pid)
    name, exe = info.get("name", ""), info.get("exe")
    if not exe:
        return False, name, "Executable path is unavailable."
    if not _kill_process(pid):
        return False, name, "Process could not be terminated."
    time.sleep(0.8)
    if _launch_detached([exe], cwd=os.path.dirname(exe) or None):
        return True, name, ""
    return False, name, "The process could not be started again."

def _open_process_location(pid):
    info = _process_info(pid)
    exe = info.get("exe")
    if not exe or not os.path.exists(exe):
        return False
    return _launch_detached(["explorer.exe", "/select,{}".format(exe)])

def _last_keyboard_identifier(gesture):
    """The generic keyboard identifier of a gesture ("kb:nvda+shift+c"), or "" if it is not a key."""
    identifiers = getattr(gesture, "normalizedIdentifiers", None) or getattr(gesture, "identifiers", ())
    for identifier in reversed(list(identifiers)):
        identifier = str(identifier).lower().replace(" ", "")
        if identifier.startswith("kb:"):
            return identifier
    return ""

# Keys that only modify other keys: pressing them must not end command mode.
_MODIFIER_NAMES = {
    "shift", "leftshift", "rightshift",
    "control", "ctrl", "leftcontrol", "rightcontrol",
    "alt", "leftalt", "rightalt",
    "windows", "leftwindows", "rightwindows",
    "nvda", "insert", "extendedinsert", "numpadinsert", "capslock",
}

def _command_key_from_gesture(gesture):
    """
    The SuperTools command a gesture stands for ("c", "shift+w", "escape"),
    or None when the gesture is not a usable command key.

    The virtual key code is used rather than the typed character, so commands
    keep working on non-Latin keyboard layouts (Persian, Arabic, Russian...).
    """
    if getattr(gesture, "isModifier", False):
        return None
    identifier = _last_keyboard_identifier(gesture)
    if not identifier:
        return None
    parts    = identifier.partition(":")[2].split("+")
    main     = parts[-1] if parts else ""
    modifier = {p for p in parts[:-1]}
    vk = getattr(gesture, "vkCode", None)
    if isinstance(vk, int):
        if vk == 0x1B:
            main = "escape"
        elif 0x41 <= vk <= 0x5A:      # A-Z, independent of the active layout
            main = chr(vk).lower()
        elif 0x30 <= vk <= 0x39:      # 0-9
            main = chr(vk)
    if not main or main in _MODIFIER_NAMES:
        return None
    if any(m in ("shift", "leftshift", "rightshift") for m in modifier):
        return "shift+" + main
    return main

# ── Feature panel (reusable) ──────────────────────────────────────────────────

# Controls NVDA announces by the label in front of them.
_NAMED_CONTROLS = ("TextCtrl", "Choice", "ComboBox", "ListBox", "CheckListBox",
                   "ListCtrl", "SpinCtrl", "RadioBox", "Slider")

def _name_controls(window):
    """
    Give every field the label that stands in front of it, as its own name.

    A screen reader has nothing to say about a text box with no name; this walks
    the finished dialog and hands each control the text of the label created
    just before it.
    """
    try:
        children = list(window.GetChildren())
    except Exception:
        return
    label = ""
    for child in children:
        _name_controls(child)
        kind = type(child).__name__
        if kind == "StaticText":
            label = child.GetLabel().strip().rstrip(":").strip()
        elif kind in _NAMED_CONTROLS:
            if label:
                try:
                    child.SetName(label)
                except Exception:
                    pass
            label = ""
        elif kind in ("Button", "CheckBox"):
            label = ""

class FeaturePanel(wx.Panel):
    """
    Standard layout for every feature tab:
    [x] Enable feature
    --- separator ---
    (feature-specific controls added via add())

    Features have no shortcuts of their own: everything is reached through
    command mode (NVDA+Shift+U) or through this dialog.
    """
    def __init__(self, parent, feature_key):
        super().__init__(parent)
        self._feature_key = feature_key

        self._outer = wx.BoxSizer(wx.VERTICAL)

        # Enable checkbox
        self._enabledChk = wx.CheckBox(self, label=_("Enable this feature"))
        self._enabledChk.SetValue(_cfg_get_bool(feature_key + "_enabled", True))
        self._outer.Add(self._enabledChk, 0, wx.ALL, 8)

        self._outer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Content area for feature-specific controls
        self._content = wx.BoxSizer(wx.VERTICAL)
        self._outer.Add(self._content, 1, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(self._outer)

    def addAppRules(self):
        """Where this feature applies: everywhere, or only / never in some apps."""
        box = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Applications")), wx.VERTICAL)
        self._appMode = wx.Choice(self, choices=[_("In every application"),
                                                 _("Only in these applications"),
                                                 _("In every application except these")])
        mode = _cfg_get_str(self._feature_key + "_app_mode", "all")
        self._appMode.SetSelection(APP_MODES.index(mode) if mode in APP_MODES else 0)
        box.Add(self._appMode, 0, wx.EXPAND | wx.ALL, 4)
        box.Add(wx.StaticText(self, label=_("Application names, separated by commas:")),
                0, wx.LEFT, 4)
        self._apps = wx.TextCtrl(self, value=_cfg_get_str(self._feature_key + "_apps", ""))
        box.Add(self._apps, 0, wx.EXPAND | wx.ALL, 4)
        choose = wx.Button(self, label=_("Choose from the programs running now..."))
        choose.Bind(wx.EVT_BUTTON, self._onChooseApps)
        box.Add(choose, 0, wx.ALL, 4)
        box.Add(wx.StaticText(self, label=_("For example: notepad, chrome, telegram")),
                0, wx.LEFT | wx.BOTTOM, 4)
        self.addSizer(box)

    def _onChooseApps(self, evt):
        chosen = [name.strip().lower() for name in self._apps.GetValue().split(",") if name.strip()]
        dlg = ApplicationPicker(self, chosen)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self._apps.SetValue(", ".join(dlg.getChosen()))
        finally:
            dlg.Destroy()

    def add(self, ctrl, flag=wx.EXPAND | wx.BOTTOM, border=6):
        self._content.Add(ctrl, 0, flag, border)
        return ctrl

    def addSizer(self, sizer, flag=wx.EXPAND | wx.BOTTOM, border=6):
        self._content.Add(sizer, 0, flag, border)

    def save(self):
        _cfg_set(self._feature_key + "_enabled", bool(self._enabledChk.GetValue()))
        if getattr(self, "_appMode", None) is not None:
            _cfg_set(self._feature_key + "_app_mode",
                     APP_MODES[max(0, self._appMode.GetSelection())])
            _cfg_set(self._feature_key + "_apps", self._apps.GetValue())
            _forget_app_rules()

    def is_enabled(self):
        return self._enabledChk.GetValue()

# ── Settings dialog ───────────────────────────────────────────────────────────

class SettingsDialog(gui.settingsDialogs.SettingsDialog):

    @property
    def title(self):
        return _("SuperTools Settings")

    def makeSettings(self, sizer):
        self._layouts = _get_installed_layouts()
        nb = wx.Notebook(self)

        nb.AddPage(self._makeTabKeyboard(nb),   _("Layout Fixer"))
        nb.AddPage(self._makeTabWordMonitor(nb), _("Word Monitor"))
        nb.AddPage(self._makeTabSystem(nb),      _("System"))
        nb.AddPage(self._makeTabGeneral(nb),     _("General"))

        sizer.Add(nb, 1, wx.EXPAND | wx.ALL, 4)
        self._nb = nb

    # ── Tab: Layout Fixer ─────────────────────────────────────────────────────
    def _makeTabKeyboard(self, parent):
        self._kbPanel = FeaturePanel(parent, "kb")

        box = wx.StaticBoxSizer(wx.StaticBox(self._kbPanel, label=_("Keyboard layouts")),
                                wx.VERTICAL)
        box.Add(wx.StaticText(self._kbPanel, label=_(
            "C moves the text to the next layout in this list. The text itself says "
            "which one it was typed with, so nothing has to be chosen; press C again to "
            "carry on to the next one.")), 0, wx.ALL, 4)
        self._layoutList = wx.CheckListBox(
            self._kbPanel, name=_("Keyboard layouts"),
            choices=[name for name, _lcid, _hkl in self._layouts])
        chosen = [code.strip().lower() for code in _cfg_get_str("kb_layouts", "").split(",")
                  if code.strip()]
        for index, (_name, lcid, _hkl) in enumerate(self._layouts):
            self._layoutList.Check(index, not chosen or lcid.lower() in chosen)
        box.Add(self._layoutList, 0, wx.EXPAND | wx.ALL, 4)
        box.Add(wx.StaticText(self._kbPanel, label=_(
            "Every layout is used unless you untick it. At least two are needed.")),
            0, wx.LEFT | wx.BOTTOM, 4)
        self._kbPanel.addSizer(box)

        self._sayLayout = self._kbPanel.add(wx.CheckBox(
            self._kbPanel, label=_("Say which layout the text was converted to")))
        self._sayLayout.SetValue(_cfg_get_bool("convert_say_layout", False))

        self._kbRestoreClip = self._kbPanel.add(
            wx.CheckBox(self._kbPanel, label=_("Put the previous clipboard content back after converting")))
        self._kbRestoreClip.SetValue(_cfg_get_bool("clipboard_restore", True))
        self._kbAnnounce = self._kbPanel.add(
            wx.CheckBox(self._kbPanel, label=_("Say the converted text")))
        self._kbAnnounce.SetValue(_cfg_get_bool("convert_announce", True))
        self._kbPanel.add(wx.StaticText(self._kbPanel, label=_("Shift+C converts the word before the cursor, without selecting it")))
        self._kbPanel.add(wx.StaticText(self._kbPanel, label=_("Z undoes the last conversion")))

        check_box = wx.StaticBoxSizer(
            wx.StaticBox(self._kbPanel, label=_("While typing")), wx.VERTICAL)
        self._autoCheck = wx.CheckBox(self._kbPanel, label=_(
            "Watch for words typed with the wrong layout"))
        self._autoCheck.SetValue(_cfg_get_bool("autocheck_enabled", False))
        check_box.Add(self._autoCheck, 0, wx.ALL, 4)
        self._autoConvert = wx.CheckBox(self._kbPanel, label=_(
            "Convert such a word at once, instead of only warning with a sound"))
        self._autoConvert.SetValue(_cfg_get_bool("autocheck_convert", False))
        check_box.Add(self._autoConvert, 0, wx.ALL, 4)
        length_row = wx.BoxSizer(wx.HORIZONTAL)
        length_row.Add(wx.StaticText(self._kbPanel, label=_("Shortest word to check:")),
                       0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._autoLength = wx.SpinCtrl(self._kbPanel, min=2, max=12,
                                       initial=_cfg_get_int("autocheck_min_length", 3))
        length_row.Add(self._autoLength, 0)
        check_box.Add(length_row, 0, wx.ALL, 4)
        check_box.Add(wx.StaticText(self._kbPanel, label=_(
            "A Latin word with no vowel at all is treated as suspicious.")), 0, wx.ALL, 4)
        self._kbPanel.addSizer(check_box)

        self._kbPanel.addAppRules()
        self._kbPanel.Layout()
        return self._kbPanel

    # ── Tab: Word Monitor ─────────────────────────────────────────────
    # Every beep, prefix and matching option belongs to a word or to a category,
    # so this tab only switches the feature on and opens the word manager.
    def _makeTabWordMonitor(self, parent):
        self._wmPanel = FeaturePanel(parent, "wm")

        self._wmEnabledChk = self._wmPanel.add(
            wx.CheckBox(self._wmPanel, label=_("Enable word monitor")))
        self._wmEnabledChk.SetValue(_get_monitor_enabled())

        manageBtn = self._wmPanel.add(
            wx.Button(self._wmPanel, label=_("Manage words...")))
        manageBtn.Bind(wx.EVT_BUTTON, self._onManageWords)

        self._wmPanel.add(wx.StaticText(
            self._wmPanel, label=_("Default settings for words added to this category")))

        self._wmPanel.addAppRules()
        self._wmPanel.Layout()
        return self._wmPanel

    def _onManageWords(self, e):
        d = WordListDialog(self, _get_word_categories())
        try:
            if d.ShowModal() == wx.ID_OK:
                _set_word_categories(d.getCategories())
        finally:
            d.Destroy()

    # ── Tab: System ──────────────────────────────────────────────────────
    # Only the options live here; the process list itself is the Process Manager
    # dialog, which this tab opens.
    def _makeTabSystem(self, parent):
        self._pmPanel = FeaturePanel(parent, "pm")
        panel = self._pmPanel

        openBtn = panel.add(wx.Button(panel, label=_("Open the Process Manager") +
                                      "  (NVDA+Shift+U, P)"))
        openBtn.Bind(wx.EVT_BUTTON, self._onOpenProcessManager)

        sort_row = wx.BoxSizer(wx.HORIZONTAL)
        sort_row.Add(wx.StaticText(panel, label=_("Sort the list by:")),
                     0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._pmSort = wx.Choice(panel, choices=[_("Name"), _("Memory use"), _("CPU"), _("PID")])
        saved_sort = _cfg_get_str("pm_sort", PM_SORT_KEYS[0])
        self._pmSort.SetSelection(PM_SORT_KEYS.index(saved_sort)
                                  if saved_sort in PM_SORT_KEYS else 0)
        sort_row.Add(self._pmSort, 0)
        panel.addSizer(sort_row)

        self._pmAuto = panel.add(wx.CheckBox(panel, label=_("Refresh the list automatically")))
        self._pmAuto.SetValue(_cfg_get_bool("pm_autorefresh_enabled", False))
        auto_row = wx.BoxSizer(wx.HORIZONTAL)
        auto_row.Add(wx.StaticText(panel, label=_("Every (seconds):")),
                     0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._pmAutoSecs = wx.SpinCtrl(panel, min=1, max=300,
                                       initial=_cfg_get_int("pm_autorefresh_seconds", 5))
        auto_row.Add(self._pmAutoSecs, 0)
        panel.addSizer(auto_row)

        self._pmConfirm = panel.add(wx.CheckBox(
            panel, label=_("Ask before ending or restarting every filtered process")))
        self._pmConfirm.SetValue(_cfg_get_bool("pm_confirm_bulk", True))

        panel.addAppRules()
        panel.Layout()
        return panel

    def _onOpenProcessManager(self, evt):
        # Save what this tab holds first, so the dialog opens with it applied.
        self._savePmOptions()
        if _plugin:
            wx.CallAfter(_plugin._showProcessManager)

    def _savePmOptions(self):
        _cfg_set("pm_sort", PM_SORT_KEYS[max(0, self._pmSort.GetSelection())])
        _cfg_set("pm_autorefresh_enabled", bool(self._pmAuto.GetValue()))
        _cfg_set("pm_autorefresh_seconds", self._pmAutoSecs.GetValue())
        _cfg_set("pm_confirm_bulk", bool(self._pmConfirm.GetValue()))

    # ── Tab: General ──────────────────────────────────────────────────────────
    def _makeTabGeneral(self, parent):
        pnl = wx.ScrolledWindow(parent)
        pnl.SetScrollRate(0, 10)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Command mode
        cmd_box = wx.StaticBoxSizer(wx.StaticBox(pnl, label="Command Mode"), wx.VERTICAL)
        self._cmdSounds = wx.CheckBox(pnl, label="Play a different beep for each command")
        self._cmdSounds.SetValue(_cfg_get_bool("command_sounds", True))
        cmd_box.Add(self._cmdSounds, 0, wx.ALL, 5)

        self._useLock = wx.CheckBox(pnl, label=_("L locks and unlocks the keyboard"))
        self._useLock.SetValue(_cfg_get_bool("lock_enabled", True))
        cmd_box.Add(self._useLock, 0, wx.ALL, 5)
        cmd_box.Add(wx.StaticText(pnl, label=_(
            "While the keyboard is locked nothing reaches any program, not even NVDA. "
            "The only key that still works is the one that opens command mode, so "
            "pressing it and then L unlocks the keyboard again. A lock never survives "
            "NVDA being restarted.")), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self._useClock = wx.CheckBox(pnl, label=_("T checks whether the clock is right"))
        self._useClock.SetValue(_cfg_get_bool("clock_enabled", True))
        cmd_box.Add(self._useClock, 0, wx.ALL, 5)

        self._cmdTimeout = wx.CheckBox(pnl, label=_("Leave command mode automatically when no key is pressed"))
        self._cmdTimeout.SetValue(_cfg_get_bool("command_timeout_enabled", True))
        cmd_box.Add(self._cmdTimeout, 0, wx.ALL, 5)
        timeout_row = wx.BoxSizer(wx.HORIZONTAL)
        timeout_row.Add(wx.StaticText(pnl, label=_("Seconds to wait:")),
                        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self._cmdTimeoutSecs = wx.SpinCtrl(pnl, min=1, max=120,
                                           initial=_cfg_get_int("command_timeout_seconds", 8))
        timeout_row.Add(self._cmdTimeoutSecs, 0)
        cmd_box.Add(timeout_row, 0, wx.ALL, 5)

        # One beep sequence per command, edited one command at a time.
        self._cmdSoundData = _get_command_sounds()
        cmd_box.Add(wx.StaticText(pnl, label="Sound for each command:"), 0, wx.LEFT | wx.TOP, 5)
        self._cmdChoice = wx.Choice(pnl, choices=[label for _k, label in COMMAND_SOUND_ITEMS])
        self._cmdChoice.SetSelection(0)
        self._cmdChoice.Bind(wx.EVT_CHOICE, self._onCmdSoundSelect)
        cmd_box.Add(self._cmdChoice, 0, wx.EXPAND | wx.ALL, 5)

        dial = wx.FlexGridSizer(2, 4, 4, 6)
        dials = {}
        for key, label, low, high, start in (
                ("count", _("Number of beeps:"), 1, 10, 1),
                ("freq", _("Frequency (Hz):"), 50, 8000, 523),
                ("step", _("Frequency change per beep (Hz):"), -2000, 2000, 0),
                ("duration", _("Duration (ms):"), 10, 3000, 70)):
            dial.Add(wx.StaticText(pnl, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            dials[key] = wx.SpinCtrl(pnl, min=low, max=high, initial=start,
                                     name=label.rstrip(":"))
            dials[key].Bind(wx.EVT_SPINCTRL, self._onCmdDial)
            dial.Add(dials[key], 0)
        self._cmdCount, self._cmdFreq = dials["count"], dials["freq"]
        self._cmdStep, self._cmdDuration = dials["step"], dials["duration"]
        cmd_box.Add(dial, 0, wx.ALL, 5)

        seq_row = wx.BoxSizer(wx.HORIZONTAL)
        seq_row.Add(wx.StaticText(pnl, label=_("Custom sequence (frequency,duration; ...):")),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self._cmdSeq = wx.TextCtrl(pnl, size=(200, -1))
        self._cmdSeq.Bind(wx.EVT_KILL_FOCUS, self._onCmdSoundEdit)
        seq_row.Add(self._cmdSeq, 1)
        cmd_box.Add(seq_row, 0, wx.EXPAND | wx.ALL, 5)
        cmd_box.Add(wx.StaticText(pnl, label=_("Leave empty to use the four settings above.")),
                    0, wx.LEFT | wx.BOTTOM, 5)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        testBtn = wx.Button(pnl, label=_("Test"))
        testBtn.Bind(wx.EVT_BUTTON, self._onCmdSoundTest)
        resetSoundsBtn = wx.Button(pnl, label="Restore default command sounds")
        resetSoundsBtn.Bind(wx.EVT_BUTTON, self._onCmdSoundReset)
        btn_row.Add(testBtn, 0, wx.RIGHT, 4); btn_row.Add(resetSoundsBtn, 0)
        cmd_box.Add(btn_row, 0, wx.ALL, 5)
        self._showCmdSound()
        vbox.Add(cmd_box, 0, wx.EXPAND | wx.ALL, 6)

        # Sounds
        sound_box = wx.StaticBoxSizer(wx.StaticBox(pnl, label=_("Sounds")), wx.VERTICAL)
        self._themes = _theme_items()
        self._themeChoice = wx.Choice(pnl, choices=[label for _id, label in self._themes])
        current = _cfg_get_str("sound_theme", THEME_NONE)
        self._themeChoice.SetSelection(next((i for i, (tid, _l) in enumerate(self._themes)
                                             if tid == current), 0))
        self._themeChoice.Bind(wx.EVT_CHOICE, self._onThemeChosen)
        sound_box.Add(self._themeChoice, 0, wx.EXPAND | wx.ALL, 5)
        self._themeAbout = wx.StaticText(pnl, label="")
        sound_box.Add(self._themeAbout, 0, wx.LEFT | wx.BOTTOM, 5)
        theme_row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("Test"), self._onThemeTest),
                               (_("Create a sound theme..."), self._onThemeWizard),
                               (_("Open the theme folder"), self._onThemeFolder),
                               (_("Save a theme template..."), self._onThemeTemplate)):
            button = wx.Button(pnl, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            theme_row.Add(button, 0, wx.RIGHT, 4)
        sound_box.Add(theme_row, 0, wx.ALL, 5)
        sound_box.Add(wx.StaticText(pnl, label=_(
            "A theme gives every sound of the add-on its own voice: beeps or a sound "
            "file, chosen one by one. Anything a theme leaves out keeps the built-in "
            "beep, so a theme can be as small as a single sound.")), 0, wx.ALL, 5)

        sound_box.Add(wx.StaticText(pnl, label=_("How the beeps are made:")), 0, wx.LEFT | wx.TOP, 5)
        self._beepEngine = wx.Choice(pnl, name=_("How the beeps are made"), choices=[
            _("Built in: the gaps are exact"),
            _("NVDA's own beep: sounds like the rest of NVDA")])
        engine = _cfg_get_str("beep_engine", BEEP_ENGINES[0])
        self._beepEngine.SetSelection(BEEP_ENGINES.index(engine) if engine in BEEP_ENGINES else 0)
        sound_box.Add(self._beepEngine, 0, wx.EXPAND | wx.ALL, 5)

        volume_row = wx.BoxSizer(wx.HORIZONTAL)
        for label, name, low, high, value in (
                (_("Volume of the built-in beeps (%):"), "_beepVolume", 1, 100,
                 _cfg_get_int("beep_volume", 35)),
                (_("Silence before a sequence (ms):"), "_beepLeadIn", 0, 500,
                 _cfg_get_int("beep_lead_in", 60))):
            volume_row.Add(wx.StaticText(pnl, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            control = wx.SpinCtrl(pnl, min=low, max=high, initial=value, name=label.rstrip(":"))
            setattr(self, name, control)
            volume_row.Add(control, 0, wx.RIGHT, 12)
        sound_box.Add(volume_row, 0, wx.ALL, 5)
        sound_box.Add(wx.StaticText(pnl, label=_(
            "The silence keeps the first beep from being swallowed while the sound "
            "device wakes up. Raise it if a first beep is ever missing.")), 0, wx.ALL, 5)
        vbox.Add(sound_box, 0, wx.EXPAND | wx.ALL, 6)

        # Languages
        language_box = wx.StaticBoxSizer(wx.StaticBox(pnl, label=_("Language")), wx.VERTICAL)
        language_box.Add(wx.StaticText(pnl, label=_(
            "SuperTools speaks the language NVDA is set to. You can write a translation "
            "for a language it does not have yet, see it straight away, and send the file "
            "to have it shipped with the add-on.")), 0, wx.ALL, 5)
        language_row = wx.BoxSizer(wx.HORIZONTAL)
        wizard = wx.Button(pnl, label=_("Create or continue a translation..."))
        wizard.Bind(wx.EVT_BUTTON, self._onTranslationWizard)
        language_row.Add(wizard, 0, wx.RIGHT, 4)
        if _cfg_get_str("language_override", ""):
            back = wx.Button(pnl, label=_("Go back to NVDA's language"))
            back.Bind(wx.EVT_BUTTON, self._onLanguageBack)
            language_row.Add(back, 0)
        language_box.Add(language_row, 0, wx.ALL, 5)
        vbox.Add(language_box, 0, wx.EXPAND | wx.ALL, 6)

        # Who made this
        credits = _credits_line()
        if credits:
            vbox.Add(wx.StaticText(pnl, label=credits), 0, wx.ALL, 10)

        # Updates
        update_box = wx.StaticBoxSizer(wx.StaticBox(pnl, label=_("Updates")), wx.VERTICAL)
        self._updateCheck = wx.CheckBox(pnl, label=_(
            "Look for a new version when NVDA starts"))
        self._updateCheck.SetValue(_cfg_get_bool("update_check", False))
        update_box.Add(self._updateCheck, 0, wx.ALL, 5)
        delay_row = wx.BoxSizer(wx.HORIZONTAL)
        delay_row.Add(wx.StaticText(pnl, label=_("Seconds to wait after NVDA starts:")),
                      0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self._updateDelay = wx.SpinCtrl(pnl, min=5, max=900,
                                        initial=_cfg_get_int("update_delay_seconds",
                                                             UPDATE_START_DELAY))
        delay_row.Add(self._updateDelay, 0)
        update_box.Add(delay_row, 0, wx.ALL, 5)
        checkNow = wx.Button(pnl, label=_("Check now"))
        checkNow.Bind(wx.EVT_BUTTON, self._onCheckNow)
        update_box.Add(checkNow, 0, wx.ALL, 5)
        update_box.Add(wx.StaticText(pnl, label=_(
            "The check waits until NVDA has finished starting, and then runs at most "
            "once a day. It only asks which version is the newest and shows you what "
            "changed: nothing is downloaded or installed unless you choose to, and a "
            "version you skip is not brought up again. If you installed SuperTools "
            "from NVDA's Add-on Store, the store already keeps it up to date.")),
            0, wx.ALL, 5)
        forget = wx.Button(pnl, label=_("Offer skipped versions again"))
        forget.Bind(wx.EVT_BUTTON, self._onForgetSkipped)
        update_box.Add(forget, 0, wx.ALL, 5)
        vbox.Add(update_box, 0, wx.EXPAND | wx.ALL, 6)

        # Backup
        backup_box = wx.StaticBoxSizer(wx.StaticBox(pnl, label=_("SuperTools Settings")), wx.VERTICAL)
        self._weeklyBackup = wx.CheckBox(pnl, label=_("Keep a weekly backup of the settings"))
        self._weeklyBackup.SetValue(_cfg_get_bool("backup_weekly", True))
        backup_box.Add(self._weeklyBackup, 0, wx.ALL, 4)
        folderBtn = wx.Button(pnl, label=_("Open the backup folder"))
        folderBtn.Bind(wx.EVT_BUTTON, self._onBackupFolder)
        backup_box.Add(folderBtn, 0, wx.ALL, 4)
        for label, handler in ((_("Run the first-time setup again..."), self._onSetupAgain),
                               (_("Export all settings to a file..."), self._onExportSettings),
                               (_("Import settings from a file..."), self._onImportSettings),
                               (_("Help"), self._onHelp),
                               (_("Reset all settings..."), self._onReset)):
            button = wx.Button(pnl, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            backup_box.Add(button, 0, wx.ALL, 4)
        vbox.Add(backup_box, 0, wx.EXPAND | wx.ALL, 6)

        pnl.SetSizer(vbox)
        return pnl

    # ── Backup ────────────────────────────────────────────────────────
    # ── Sound themes ───────────────────────────────────────────────────────
    def _chosenTheme(self):
        return self._themes[max(0, self._themeChoice.GetSelection())][0]

    def _onThemeChosen(self, evt):
        # Apply at once, so Test plays what was just picked.
        _cfg_set("sound_theme", self._chosenTheme())
        theme = _current_theme()
        self._themeAbout.SetLabel(theme["description"] if theme else "")

    def _saveSoundSettings(self):
        _cfg_set("beep_engine", BEEP_ENGINES[max(0, self._beepEngine.GetSelection())])
        _cfg_set("beep_volume", self._beepVolume.GetValue())
        _cfg_set("beep_lead_in", self._beepLeadIn.GetValue())

    def _onThemeTest(self, evt):
        # Apply first, so Test plays what is on screen right now.
        self._saveSoundSettings()
        self._onThemeChosen(None)
        _play_event("start", _get_command_sound("start"))

    def _onThemeWizard(self, evt):
        dlg = ThemeWizard(self)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        self._refreshThemes()

    def _refreshThemes(self):
        _forget_themes()
        self._themes = _theme_items()
        self._themeChoice.Set([label for _id, label in self._themes])
        current = _cfg_get_str("sound_theme", THEME_NONE)
        self._themeChoice.SetSelection(next((i for i, (tid, _l) in enumerate(self._themes)
                                             if tid == current), 0))

    def _onTranslationWizard(self, evt):
        dlg = TranslationWizard(self)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _onLanguageBack(self, evt):
        _cfg_set("language_override", "")
        gui.messageBox(_("SuperTools will follow NVDA's language again after NVDA restarts."),
                       "SuperTools", wx.OK, self)

    def _onThemeFolder(self, evt):
        folder = _user_theme_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            _launch_detached(["explorer.exe", folder])
        except Exception as ex:
            gui.messageBox(_("File error: {e}").format(e=ex), "SuperTools",
                           wx.OK | wx.ICON_ERROR, self)

    def _onThemeTemplate(self, evt):
        path = _ask_for_file(self, _("Save a theme template..."), save=True,
                             default="mytheme.json")
        if not path:
            return
        if _run_file_task(self, _write_theme_template, path, _get_command_sounds()):
            _forget_themes()

    def _onForgetSkipped(self, evt):
        _cfg_set("update_skip", "")
        ui.message(_("Skipped versions will be offered again."))

    def _onCheckNow(self, evt):
        _cfg_set("update_check", bool(self._updateCheck.GetValue()))
        ui.message(_("Looking for a new version..."))
        if _plugin:
            _plugin._checkForUpdate(announce=True)

    def _onSetupAgain(self, evt):
        dlg = SetupWizard(self)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                dlg.save()
                gui.messageBox(_("Done. Close and open the settings to see the change."),
                               "SuperTools", wx.OK, self)
        finally:
            dlg.Destroy()

    def _onBackupFolder(self, evt):
        folder = _backup_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            _launch_detached(["explorer.exe", folder])
        except Exception as ex:
            gui.messageBox(_("File error: {e}").format(e=ex), "SuperTools",
                           wx.OK | wx.ICON_ERROR, self)

    def _onExportSettings(self, evt):
        path = _ask_for_file(self, _("Export all settings to a file..."), save=True,
                             default="superTools-backup.json")
        if path and _run_file_task(self, _export_settings, path):
            gui.messageBox(_("Settings exported."), "SuperTools", wx.OK, self)

    def _onImportSettings(self, evt):
        path = _ask_for_file(self, _("Import settings from a file..."))
        if not path:
            return
        result = _run_file_task(self, _import_settings, path)
        if result is None:
            return
        if not result:
            gui.messageBox(_("This file does not contain SuperTools settings."),
                           "SuperTools", wx.OK | wx.ICON_ERROR, self)
            return
        gui.messageBox(_("Settings imported."), "SuperTools", wx.OK, self)
        # The dialog now shows the old values, so close it without saving them back.
        self.onCancel(None)

    # ── Command sounds ────────────────────────────────────────────────────────
    def _currentCmdKey(self):
        index = self._cmdChoice.GetSelection()
        if index == wx.NOT_FOUND:
            index = 0
        return COMMAND_SOUND_ITEMS[index][0]

    def _showCmdSound(self):
        key = self._currentCmdKey()
        beeps = self._cmdSoundData.get(key) or [[523, 70]]
        # Beeps that follow a pattern go into the controls; anything else is
        # shown as the sequence it is, so nothing the user wrote is lost.
        steps = {beeps[i + 1][0] - beeps[i][0] for i in range(len(beeps) - 1)}
        uniform = len({d for _f, d in beeps}) == 1 and len(steps) <= 1
        self._cmdCount.SetValue(len(beeps))
        self._cmdFreq.SetValue(beeps[0][0])
        self._cmdStep.SetValue(steps.pop() if steps else 0)
        self._cmdDuration.SetValue(beeps[0][1])
        self._cmdSeq.ChangeValue("" if uniform else _format_beep_text(beeps))

    def _onCmdDial(self, evt):
        """The controls win over the text box, which is for the unusual cases."""
        self._cmdSeq.ChangeValue("")
        self._cmdSoundData[self._currentCmdKey()] = _build_beeps(
            self._cmdCount.GetValue(), self._cmdFreq.GetValue(),
            self._cmdDuration.GetValue(), self._cmdStep.GetValue())

    def _onCmdSoundSelect(self, evt):
        self._showCmdSound()

    def _onCmdSoundEdit(self, evt):
        key = self._currentCmdKey()
        written = self._cmdSeq.GetValue().strip()
        if written:
            self._cmdSoundData[key] = _parse_beep_text(written, COMMAND_SOUND_DEFAULTS.get(key))
        else:
            self._cmdSoundData[key] = _build_beeps(
                self._cmdCount.GetValue(), self._cmdFreq.GetValue(),
                self._cmdDuration.GetValue(), self._cmdStep.GetValue())
        if evt:
            evt.Skip()

    def _onCmdSoundTest(self, evt):
        self._onCmdSoundEdit(None)
        _play_sequence(self._cmdSoundData[self._currentCmdKey()])

    def _onCmdSoundReset(self, evt):
        self._cmdSoundData = {k: [list(b) for b in v] for k, v in COMMAND_SOUND_DEFAULTS.items()}
        self._showCmdSound()

    def _onHelp(self, evt):
        dlg = HelpDialog(self)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _onReset(self, e):
        if gui.messageBox(_("All SuperTools settings will be erased. Continue?"), _("Reset Settings"),
                          wx.YES_NO | wx.ICON_WARNING, self) == wx.YES:
            _cfg_reset()
            gui.messageBox(_("Settings have been reset."), _("Reset Settings"), wx.OK, self)
            # NVDA settings dialogs are not modal: they are closed through
            # onCancel, which destroys the window. EndModal would leave the
            # dialog alive and block every later attempt to open it.
            self.onCancel(None)

    def postInit(self):
        self._nb.SetFocus()

    def onOk(self, evt):
        # Layout Fixer: at least two layouts have to remain in the ring.
        ticked = [self._layouts[i][1] for i in range(len(self._layouts))
                  if self._layoutList.IsChecked(i)]
        if self._kbPanel.is_enabled() and len(self._layouts) >= 2 and len(ticked) < 2:
            gui.messageBox(_("Tick at least two keyboard layouts, or switch the Layout "
                             "Fixer off."), "SuperTools", wx.OK | wx.ICON_ERROR, self)
            self._nb.SetSelection(0)
            self._layoutList.SetFocus()
            return

        self._kbPanel.save()
        # Everything ticked means "all of them", and keeps working when the user
        # adds a keyboard to Windows later.
        _cfg_set("kb_layouts", "" if len(ticked) == len(self._layouts) else ",".join(ticked))
        _cfg_set("convert_say_layout", bool(self._sayLayout.GetValue()))

        # Layout Fixer options
        _cfg_set("clipboard_restore", bool(self._kbRestoreClip.GetValue()))
        _cfg_set("convert_announce",  bool(self._kbAnnounce.GetValue()))
        _cfg_set("autocheck_enabled", bool(self._autoCheck.GetValue()))
        _cfg_set("autocheck_convert", bool(self._autoConvert.GetValue()))
        _cfg_set("autocheck_min_length", self._autoLength.GetValue())

        # Word Monitor
        self._wmPanel.save()
        _set_monitor_enabled(bool(self._wmEnabledChk.GetValue()))

        # System
        self._pmPanel.save()
        self._savePmOptions()

        # General
        _cfg_set("sound_theme", self._chosenTheme())
        self._saveSoundSettings()
        _forget_themes()
        _cfg_set("update_check", bool(self._updateCheck.GetValue()))
        _cfg_set("backup_weekly", bool(self._weeklyBackup.GetValue()))
        _cfg_set("command_timeout_enabled", bool(self._cmdTimeout.GetValue()))
        _cfg_set("command_timeout_seconds", self._cmdTimeoutSecs.GetValue())
        _cfg_set("lock_enabled", bool(self._useLock.GetValue()))
        _cfg_set("clock_enabled", bool(self._useClock.GetValue()))
        _cfg_set("update_delay_seconds", self._updateDelay.GetValue())
        _cfg_set("command_sounds", bool(self._cmdSounds.GetValue()))
        self._onCmdSoundEdit(None)
        _set_command_sounds(self._cmdSoundData)

        self._releaseReferences()
        super().onOk(evt)

    def onCancel(self, evt):
        self._releaseReferences()
        super().onCancel(evt)

    def _releaseReferences(self):
        """
        Drop what the dialog holds, so the destroyed window can be collected.
        A surviving instance makes NVDA refuse to open the dialog again with
        "Cannot open new settings dialog while instance still exists".
        """
        self._layouts = []
        self._pmAllProcs = []
        self._cmdSoundData = None
        try:
            self._pmList._filtered = []
        except Exception:
            pass

def _release_settings_instances():
    """
    Make NVDA forget settings dialogs that have already been destroyed.

    NVDA keeps every settings dialog in a table and refuses to open a new one
    while an old instance is still alive. A destroyed dialog normally stays in
    memory until the garbage collector runs, which is why opening the settings
    used to fail at random. Returns True when a retry makes sense.
    """
    gc.collect()
    try:
        instances = gui.settingsDialogs.SettingsDialog._instances
        destroyed_state = getattr(
            getattr(gui.settingsDialogs.SettingsDialog, "DialogState", None), "DESTROYED", None)
    except Exception:
        log.debugWarning("SuperTools: settings dialog registry is unavailable", exc_info=True)
        return False
    stale = []
    for dlg in list(instances.keys()):
        if not isinstance(dlg, SettingsDialog):
            continue
        if destroyed_state is not None and instances.get(dlg) == destroyed_state:
            stale.append(dlg); continue
        try:
            dlg.IsShown()          # raises once the window itself is gone
        except RuntimeError:
            stale.append(dlg)
        except Exception:
            pass
    for dlg in stale:
        instances.pop(dlg, None)
    # Either the collector freed the old dialog, or it has just been dropped.
    return True

# ── Choosing applications ───────────────────────────────────────────────

class ApplicationPicker(wx.Dialog):
    """
    Tick the programs a rule applies to, instead of typing their names.
    The list is what is running now, which is how someone thinks about it:
    "this one, the one I am using".
    """
    def __init__(self, parent, chosen):
        super().__init__(parent, title=_("Choose applications"), size=(460, 520),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(wx.StaticText(panel, label=_("Programs running now:")), 0, wx.ALL, 8)

        seen, self._names = set(), []
        for _pid, name, _memory, _cpu, _publisher in _get_process_rows():
            plain = name.lower().replace(".exe", "")
            if plain and plain not in seen:
                seen.add(plain)
                self._names.append(plain)
        for name in sorted(n for n in chosen if n not in seen):
            self._names.append(name)
        self._names.sort()

        self._list = wx.CheckListBox(panel, choices=self._names)
        for index, name in enumerate(self._names):
            self._list.Check(index, name in chosen)
        box.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(panel, label=_("Or type a name:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._typed = wx.TextCtrl(panel)
        row.Add(self._typed, 1)
        add = wx.Button(panel, label=_("Add"))
        add.Bind(wx.EVT_BUTTON, self._onAdd)
        row.Add(add, 0, wx.LEFT, 4)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(panel, wx.ID_OK, _("OK")); cancel = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        buttons.AddButton(ok); buttons.AddButton(cancel); buttons.Realize()
        box.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        panel.SetSizer(box)
        outer = wx.BoxSizer(wx.VERTICAL); outer.Add(panel, 1, wx.EXPAND); self.SetSizer(outer)
        _name_controls(self)
        self.CenterOnScreen()
        self._list.SetFocus()

    def _onAdd(self, evt):
        name = self._typed.GetValue().strip().lower().replace(".exe", "")
        if name and name not in self._names:
            self._names.append(name)
            self._list.Append(name)
            self._list.Check(len(self._names) - 1, True)
        self._typed.SetValue("")

    def getChosen(self):
        return [self._names[i] for i in range(len(self._names)) if self._list.IsChecked(i)]

# ── The first run ─────────────────────────────────────────────────────

class SetupWizard(wx.Dialog):
    """
    The few decisions that make the add-on useful, asked once, in order, with a
    sensible answer already filled in. Everything here can be changed later in
    the settings; nobody has to come back to this screen.
    """
    def __init__(self, parent):
        super().__init__(parent, title=_("Welcome to SuperTools"), size=(620, 620),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._layouts = _get_installed_layouts()
        panel = wx.ScrolledWindow(self)
        panel.SetScrollRate(0, 10)
        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(wx.StaticText(panel, label=_(
            "Everything in SuperTools is reached by pressing NVDA+Shift+U and then one "
            "key. Press H after that for the full list at any time.\n\n"
            "Three questions, and you are set up.")), 0, wx.ALL, 10)

        # 1: what to switch on
        features = wx.StaticBoxSizer(wx.StaticBox(panel, label=_("1. What do you want to use?")),
                                     wx.VERTICAL)
        self._useKb = wx.CheckBox(panel, label=_(
            "Layout Fixer: repair text typed with the wrong keyboard layout (C)"))
        self._useWm = wx.CheckBox(panel, label=_(
            "Word Monitor: give chosen words their own sound when NVDA says them (W)"))
        self._usePm = wx.CheckBox(panel, label=_(
            "Process Manager: see and manage running programs (P)"))
        for control in (self._useKb, self._useWm, self._usePm):
            control.SetValue(True)
            features.Add(control, 0, wx.ALL, 5)
        box.Add(features, 0, wx.EXPAND | wx.ALL, 8)

        # 2: which keyboards take part
        layouts = wx.StaticBoxSizer(wx.StaticBox(panel, label=_(
            "2. Which keyboard layouts do you use?")), wx.VERTICAL)
        layouts.Add(wx.StaticText(panel, label=_(
            "C moves the text to the next one in this list, and the text itself says "
            "which one it came from. Leave them all ticked unless one should be left "
            "out.")), 0, wx.ALL, 5)
        self._layoutList = wx.CheckListBox(
            panel, name=_("Keyboard layouts"),
            choices=[name for name, _lcid, _hkl in self._layouts])
        for index in range(len(self._layouts)):
            self._layoutList.Check(index, True)
        layouts.Add(self._layoutList, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(layouts, 0, wx.EXPAND | wx.ALL, 8)

        # 3: how it should sound
        sounds = wx.StaticBoxSizer(wx.StaticBox(panel, label=_("3. How should it sound?")),
                                   wx.VERTICAL)
        self._themes = _theme_items()
        self._theme = wx.Choice(panel, choices=[label for _id, label in self._themes])
        self._theme.SetSelection(0)
        self._theme.Bind(wx.EVT_CHOICE, self._onTheme)
        sounds.Add(self._theme, 0, wx.EXPAND | wx.ALL, 5)
        test = wx.Button(panel, label=_("Test"))
        test.Bind(wx.EVT_BUTTON, self._onTheme)
        sounds.Add(test, 0, wx.ALL, 5)
        box.Add(sounds, 0, wx.EXPAND | wx.ALL, 8)

        box.Add(wx.StaticText(panel, label=_(
            "That is all. Everything else, and much more, is in the settings: "
            "NVDA+Shift+U, then S.")), 0, wx.ALL, 10)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(panel, wx.ID_OK, _("Finish"))
        later = wx.Button(panel, wx.ID_CANCEL, _("Skip for now"))
        buttons.AddButton(ok); buttons.AddButton(later); buttons.Realize()
        box.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(box)
        outer = wx.BoxSizer(wx.VERTICAL); outer.Add(panel, 1, wx.EXPAND); self.SetSizer(outer)
        _name_controls(self)
        self.CenterOnScreen()
        self._useKb.SetFocus()

    def _onTheme(self, evt):
        _cfg_set("sound_theme", self._themes[max(0, self._theme.GetSelection())][0])
        _forget_themes()
        _play_event("start", _get_command_sound("start"))

    def save(self):
        _cfg_set("kb_enabled", bool(self._useKb.GetValue()))
        _cfg_set("wm_enabled", bool(self._useWm.GetValue()))
        _cfg_set("pm_enabled", bool(self._usePm.GetValue()))
        ticked = [self._layouts[i][1] for i in range(len(self._layouts))
                  if self._layoutList.IsChecked(i)]
        _cfg_set("kb_layouts", "" if len(ticked) == len(self._layouts) else ",".join(ticked))
        _cfg_set("sound_theme", self._themes[max(0, self._theme.GetSelection())][0])
        _cfg_set("setup_done", "1")
        _forget_themes()

# ── Wizards ───────────────────────────────────────────────────────────
# Making a language or a sound theme should not need a text editor, a build or
# a checkout: both wizards write the same files a contributor would send us.

class TranslationWizard(wx.Dialog):
    """
    Translate the add-on text by text. The work is saved as a .po file, the one
    to send to the author, and can be tried out at once without restarting NVDA
    in that language.
    """
    def __init__(self, parent):
        super().__init__(parent, title=_("Create or continue a translation"),
                         size=(720, 620), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._texts = _pot_texts()
        self._entries = {}
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)

        about = wx.FlexGridSizer(3, 2, 4, 6)
        about.AddGrowableCol(1, 1)
        fields = {}
        for key, label, value in (("code", _("Language code (fa, de, pt_BR...):"), _nvda_language()),
                                  ("name", _("Language name, as its speakers write it:"), ""),
                                  ("translator", _("Your name, for the credits:"), "")):
            about.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            fields[key] = wx.TextCtrl(panel, value=value, name=label.rstrip(":"))
            about.Add(fields[key], 0, wx.EXPAND)
        self._code, self._name, self._translator = fields["code"], fields["name"], fields["translator"]
        box.Add(about, 0, wx.EXPAND | wx.ALL, 8)
        load = wx.Button(panel, label=_("Load what I translated before"))
        load.Bind(wx.EVT_BUTTON, self._onLoad)
        box.Add(load, 0, wx.LEFT | wx.BOTTOM, 8)

        box.Add(wx.StaticText(panel, label=_("Texts:")), 0, wx.LEFT, 8)
        self._list = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._list.Bind(wx.EVT_LISTBOX, self._onSelect)
        box.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        self._english = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 60))
        box.Add(wx.StaticText(panel, label=_("English:")), 0, wx.LEFT, 8)
        box.Add(self._english, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        box.Add(wx.StaticText(panel, label=_("Your translation:")), 0, wx.LEFT | wx.TOP, 8)
        self._translation = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 60))
        self._translation.Bind(wx.EVT_KILL_FOCUS, self._onTyped)
        box.Add(self._translation, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self._progress = wx.StaticText(panel, label="")
        box.Add(self._progress, 0, wx.ALL, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("Next one to do"), self._onNext),
                               (_("Copy the English text"), self._onCopyEnglish),
                               (_("Save"), self._onSave),
                               (_("Save and use it now"), self._onSaveAndUse)):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(button, 0, wx.RIGHT, 4)
        close = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        buttons.Add(close, 0)
        box.Add(buttons, 0, wx.ALL, 8)

        panel.SetSizer(box)
        outer = wx.BoxSizer(wx.VERTICAL); outer.Add(panel, 1, wx.EXPAND); self.SetSizer(outer)
        self.SetEscapeId(wx.ID_CLOSE)
        self._fill()
        _name_controls(self)
        self.CenterOnScreen()
        self._code.SetFocus()

    # ── the list ───────────────────────────────────────────────────────
    def _fill(self, select=0):
        self._list.Clear()
        for text in self._texts:
            done = self._entries.get(text)
            label = ("✓ " if done else "• ") + text.replace("\n", " ")[:70]
            self._list.Append(label)
        if self._texts:
            self._list.SetSelection(min(select, len(self._texts) - 1))
            self._onSelect(None)
        self._progress.SetLabel(_("{done} of {total} texts translated").format(
            done=sum(1 for t in self._texts if self._entries.get(t)), total=len(self._texts)))

    def _current(self):
        index = self._list.GetSelection()
        return self._texts[index] if 0 <= index < len(self._texts) else None

    def _onSelect(self, evt):
        self._onTyped(None)
        text = self._current()
        if text is None:
            return
        self._english.ChangeValue(text)
        self._translation.ChangeValue(self._entries.get(text, ""))
        self._shown = text

    def _onTyped(self, evt):
        """Keep what was typed for the text that was on screen a moment ago."""
        shown = getattr(self, "_shown", None)
        if shown is not None:
            value = self._translation.GetValue().strip()
            if value:
                self._entries[shown] = value
            else:
                self._entries.pop(shown, None)
        if evt:
            evt.Skip()

    def _onNext(self, evt):
        self._onTyped(None)
        start = self._list.GetSelection() + 1
        order = list(range(start, len(self._texts))) + list(range(0, start))
        for index in order:
            if not self._entries.get(self._texts[index]):
                self._list.SetSelection(index)
                self._onSelect(None)
                self._translation.SetFocus()
                return
        ui.message(_("Everything is translated."))

    def _onCopyEnglish(self, evt):
        text = self._current()
        if text is not None:
            self._translation.ChangeValue(text)
            self._onTyped(None)
            self._translation.SetFocus()

    # ── saving ──────────────────────────────────────────────────────────
    def _language(self):
        code = self._code.GetValue().strip().replace("-", "_") or "xx"
        return code, (self._name.GetValue().strip() or code), self._translators()

    def _translators(self):
        """
        Everyone who has worked on this language, the newcomer last.
        A translation often passes through several hands, and the ones before
        should not be rubbed out by the one saving now.
        """
        names = [name.strip() for name in getattr(self, "_before", "").split(",")
                 if name.strip()]
        mine = self._translator.GetValue().strip()
        if mine and mine not in names:
            names.append(mine)
        return ", ".join(names) or mine

    def _poPath(self):
        return os.path.join(_user_translation_dir(), self._language()[0] + ".po")

    def _onLoad(self, evt):
        path = self._poPath()
        if not os.path.isfile(path):
            path = _ask_for_file(self, _("Load what I translated before"),
                                 wildcard="*.po|*.po") or ""
        if path and os.path.isfile(path):
            self._entries = _read_po_file(path)
            # Whoever worked on this file before keeps their place in the credits.
            self._before = _read_po_header(path, "Last-Translator")
            if self._before and not self._translator.GetValue().strip():
                self._translator.ChangeValue(self._before)
            self._fill(self._list.GetSelection())
            ui.message(_("{done} of {total} texts translated").format(
                done=len(self._entries), total=len(self._texts)))

    def _save(self):
        self._onTyped(None)
        code, name, translator = self._language()
        path = self._poPath()
        _run_file_task(self, _write_po_file, path, code, name, translator,
                       self._entries, self._texts)
        return code, path

    def _onSave(self, evt):
        code, path = self._save()
        gui.messageBox(_("Saved as {path}\n\nSend this file to the author to have your "
                         "language shipped with the add-on.").format(path=path),
                       "SuperTools", wx.OK, self)

    def _onSaveAndUse(self, evt):
        code, path = self._save()
        if _run_file_task(self, _install_translation, code, self._entries) is None:
            return
        _cfg_set("language_override", code)
        _apply_language_override()
        gui.messageBox(_("Saved as {path}\n\nSuperTools will speak your language from now "
                         "on. Close and open the settings to see it. To go back to NVDA's "
                         "own language, use the button in the General tab.").format(path=path),
                       "SuperTools", wx.OK, self)

class ThemeWizard(wx.Dialog):
    """Build a sound theme sound by sound, each one beeps or a sound file."""
    def __init__(self, parent):
        super().__init__(parent, title=_("Create a sound theme"), size=(720, 640),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._sounds = {}
        self._events = list(COMMAND_SOUND_ITEMS) + [
            ("monitor_on", _("Word Monitor turned on")),
            ("monitor_off", _("Word Monitor turned off")),
            ("word", _("A word the Word Monitor found")),
        ]
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)

        about = wx.FlexGridSizer(3, 2, 4, 6)
        about.AddGrowableCol(1, 1)
        fields = {}
        for key, label in (("name", _("Theme name:")),
                           ("author", _("Your name, for the credits:")),
                           ("description", _("What it sounds like:"))):
            about.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            fields[key] = wx.TextCtrl(panel, name=label.rstrip(":"))
            about.Add(fields[key], 0, wx.EXPAND)
        self._name, self._author, self._description = (fields["name"], fields["author"],
                                                       fields["description"])
        box.Add(about, 0, wx.EXPAND | wx.ALL, 8)

        box.Add(wx.StaticText(panel, label=_("Sounds:")), 0, wx.LEFT, 8)
        self._list = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._list.Bind(wx.EVT_LISTBOX, self._onSelect)
        box.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        self._kind = wx.RadioBox(panel, label=_("This sound is:"),
                                 choices=[_("The built-in beep"), _("Beeps of my own"),
                                          _("A sound file")], style=wx.RA_SPECIFY_ROWS)
        self._kind.Bind(wx.EVT_RADIOBOX, self._onKind)
        box.Add(self._kind, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        beeps = wx.FlexGridSizer(1, 8, 4, 6)
        dials = {}
        for key, label, low, high, start in (
                ("count", _("Number of beeps:"), 1, 10, 2),
                ("freq", _("Frequency (Hz):"), 50, 8000, 523),
                ("step", _("Frequency change per beep (Hz):"), -2000, 2000, 200),
                ("duration", _("Duration (ms):"), 10, 3000, 60)):
            beeps.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            dials[key] = wx.SpinCtrl(panel, min=low, max=high, initial=start,
                                     name=label.rstrip(":"))
            beeps.Add(dials[key], 0)
        self._count, self._freq = dials["count"], dials["freq"]
        self._step, self._duration = dials["step"], dials["duration"]
        box.Add(beeps, 0, wx.ALL, 8)

        file_row = wx.BoxSizer(wx.HORIZONTAL)
        self._file = wx.TextCtrl(panel)
        file_row.Add(self._file, 1)
        browse = wx.Button(panel, label=_("Browse..."))
        browse.Bind(wx.EVT_BUTTON, self._onBrowse)
        file_row.Add(browse, 0, wx.LEFT, 4)
        box.Add(file_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("Use this for the selected sound"), self._onApply),
                               (_("Test"), self._onTest),
                               (_("Save"), self._onSave),
                               (_("Save and use it now"), self._onSaveAndUse)):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(button, 0, wx.RIGHT, 4)
        close = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        buttons.Add(close, 0)
        box.Add(buttons, 0, wx.ALL, 8)

        panel.SetSizer(box)
        outer = wx.BoxSizer(wx.VERTICAL); outer.Add(panel, 1, wx.EXPAND); self.SetSizer(outer)
        self.SetEscapeId(wx.ID_CLOSE)
        self._fill()
        _name_controls(self)
        self.CenterOnScreen()
        self._name.SetFocus()

    def _fill(self, select=0):
        self._list.Clear()
        for key, label in self._events:
            entry = self._sounds.get(key)
            if not entry:
                mark = _("built-in beep")
            elif entry.get("file"):
                mark = os.path.basename(entry["file"])
            else:
                mark = _("{n} beeps").format(n=len(entry["beeps"]))
            self._list.Append("{}  —  {}".format(label, mark))
        if self._events:
            self._list.SetSelection(min(select, len(self._events) - 1))
            self._onSelect(None)

    def _currentKey(self):
        index = self._list.GetSelection()
        return self._events[index][0] if 0 <= index < len(self._events) else None

    def _onSelect(self, evt):
        entry = self._sounds.get(self._currentKey()) or {}
        if entry.get("file"):
            self._kind.SetSelection(2)
            self._file.ChangeValue(entry["file"])
        elif entry.get("beeps"):
            self._kind.SetSelection(1)
            self._count.SetValue(len(entry["beeps"]))
            self._freq.SetValue(entry["beeps"][0][0])
            self._duration.SetValue(entry["beeps"][0][1])
        else:
            self._kind.SetSelection(0)
        self._onKind(None)

    def _onKind(self, evt):
        kind = self._kind.GetSelection()
        for control in (self._count, self._freq, self._step, self._duration):
            control.Enable(kind == 1)
        self._file.Enable(kind == 2)

    def _entry(self):
        kind = self._kind.GetSelection()
        if kind == 1:
            return {"beeps": _build_beeps(self._count.GetValue(), self._freq.GetValue(),
                                          self._duration.GetValue(), self._step.GetValue())}
        if kind == 2 and self._file.GetValue().strip():
            return {"file": self._file.GetValue().strip()}
        return None

    def _onApply(self, evt):
        key = self._currentKey()
        if key is None:
            return
        entry = self._entry()
        if entry:
            self._sounds[key] = entry
        else:
            self._sounds.pop(key, None)
        self._fill(self._list.GetSelection())

    def _onTest(self, evt):
        entry = self._entry()
        if entry and entry.get("file"):
            _play_sound_file(entry["file"])
        elif entry:
            _play_sequence(entry["beeps"], 20)
        else:
            _play_sequence(_get_command_sound(self._currentKey() or "start"))

    def _onBrowse(self, evt):
        path = _ask_for_file(self, _("A sound file"),
                             wildcard="*.wav;*.mp3;*.ogg;*.wma|*.wav;*.mp3;*.ogg;*.wma|*.*|*.*")
        if path:
            self._file.SetValue(path)
            self._kind.SetSelection(2)
            self._onKind(None)

    def _save(self):
        self._onApply(None)
        name = self._name.GetValue().strip() or _("My theme")
        theme_id = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "mytheme"
        path = os.path.join(_user_theme_dir(), theme_id + ".json")
        data = {"name": name, "author": self._author.GetValue().strip(),
                "description": self._description.GetValue().strip(),
                "sounds": self._sounds}
        def write(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            return True
        if _run_file_task(self, write, path) is None:
            return None, None
        _forget_themes()
        return theme_id, path

    def _onSave(self, evt):
        theme_id, path = self._save()
        if path:
            gui.messageBox(_("Saved as {path}\n\nSend the file, with its sounds, to the "
                             "author to have your theme shipped with the add-on.").format(path=path),
                           "SuperTools", wx.OK, self)

    def _onSaveAndUse(self, evt):
        theme_id, path = self._save()
        if path:
            _cfg_set("sound_theme", theme_id)
            _play_event("start", _get_command_sound("start"))

# ── Word settings ────────────────────────────────────────────────────

class WordSettingsPanel(wx.Panel):
    """
    The settings that can be given to a single word, or to a category as the
    default for the words added to it: how it is matched, what happens when it
    is spoken, and exactly how the beeps sound.
    """
    def __init__(self, parent, settings):
        super().__init__(parent)
        settings = _normalize_word_settings(settings)
        box = wx.BoxSizer(wx.VERTICAL)

        # What happens when the word is spoken
        box.Add(wx.StaticText(self, label=_("When the word is spoken:")), 0, wx.TOP | wx.LEFT, 4)
        self._action = wx.Choice(self, choices=[_("Play the beeps only"), _("Say the extra text only"),
                                                _("Say the extra text and play the beeps"), _("Do not speak the word at all")])
        self._action.SetSelection(WORD_ACTIONS.index(settings["action"]))
        box.Add(self._action, 0, wx.EXPAND | wx.ALL, 4)

        box.Add(wx.StaticText(self, label=_("Text said before the word:")), 0, wx.LEFT, 4)
        self._prefix = wx.TextCtrl(self, value=settings["prefix"])
        box.Add(self._prefix, 0, wx.EXPAND | wx.ALL, 4)

        # Matching
        box.Add(wx.StaticText(self, label=_("Match:")), 0, wx.LEFT, 4)
        self._match = wx.Choice(self, choices=[_("Anywhere in the text"), _("Whole word only")])
        self._match.SetSelection(MATCH_MODES.index(settings["match"]))
        box.Add(self._match, 0, wx.EXPAND | wx.ALL, 4)
        self._case = wx.CheckBox(self, label=_("Match upper and lower case exactly"))
        self._case.SetValue(settings["case"])
        box.Add(self._case, 0, wx.ALL, 4)

        # Beeps
        beeps = settings["beeps"]
        uniform = len({(f, d) for f, d in beeps}) == 1
        grid = wx.FlexGridSizer(4, 2, 4, 6)
        grid.AddGrowableCol(1, 1)
        dials = {}
        for key, label, low, high, start in (
                ("count", _("Number of beeps:"), 1, 20, len(beeps)),
                ("freq", _("Frequency (Hz):"), 50, 8000, beeps[0][0]),
                ("dur", _("Duration (ms):"), 10, 3000, beeps[0][1]),
                ("gap", _("Gap between beeps (ms):"), 0, 5000, settings["gap"])):
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            dials[key] = wx.SpinCtrl(self, min=low, max=high, initial=start,
                                     name=label.rstrip(":"))
            grid.Add(dials[key], 0)
        self._count, self._freq = dials["count"], dials["freq"]
        self._dur, self._gap = dials["dur"], dials["gap"]
        box.Add(grid, 0, wx.EXPAND | wx.ALL, 4)

        box.Add(wx.StaticText(self, label=_("Custom sequence (frequency,duration; ...):")), 0, wx.LEFT, 4)
        self._custom = wx.TextCtrl(self, value="" if uniform else _format_beep_text(beeps))
        box.Add(self._custom, 0, wx.EXPAND | wx.ALL, 4)
        box.Add(wx.StaticText(self, label=_("Leave empty to use the four settings above.")), 0, wx.LEFT | wx.BOTTOM, 4)

        box.Add(wx.StaticText(self, label=_("Sound file instead of beeps:")), 0, wx.LEFT, 4)
        sound_row = wx.BoxSizer(wx.HORIZONTAL)
        self._sound = wx.TextCtrl(self, value=settings.get("sound", ""))
        sound_row.Add(self._sound, 1)
        browse = wx.Button(self, label=_("Browse..."))
        browse.Bind(wx.EVT_BUTTON, self._onBrowseSound)
        sound_row.Add(browse, 0, wx.LEFT, 4)
        clear = wx.Button(self, label=_("Use beeps"))
        clear.Bind(wx.EVT_BUTTON, lambda e: self._sound.SetValue(""))
        sound_row.Add(clear, 0, wx.LEFT, 4)
        box.Add(sound_row, 0, wx.EXPAND | wx.ALL, 4)

        self._interrupt = wx.CheckBox(self, label=_("Interrupt speech while beeping"))
        self._interrupt.SetValue(settings["interrupt"])
        box.Add(self._interrupt, 0, wx.ALL, 4)

        testBtn = wx.Button(self, label=_("Test"))
        testBtn.Bind(wx.EVT_BUTTON, self._onTest)
        box.Add(testBtn, 0, wx.ALL, 4)

        self._repeat = settings["repeat"]
        self.SetSizer(box)

    def getSettings(self):
        custom = self._custom.GetValue().strip()
        beeps = _parse_beep_text(custom) if custom else _build_beeps(
            self._count.GetValue(), self._freq.GetValue(), self._dur.GetValue())
        return {"sound": self._sound.GetValue().strip(),
                "action": WORD_ACTIONS[max(0, self._action.GetSelection())],
                "prefix": self._prefix.GetValue(),
                "match": MATCH_MODES[max(0, self._match.GetSelection())],
                "case": self._case.GetValue(),
                "beeps": beeps, "gap": self._gap.GetValue(),
                "repeat": self._repeat, "interrupt": self._interrupt.GetValue()}

    def enableAll(self, enabled):
        for child in self.GetChildren():
            child.Enable(enabled)

    def _onBrowseSound(self, evt):
        path = _ask_for_file(self, _("Sound file instead of beeps:"),
                             wildcard="*.wav;*.mp3;*.ogg;*.wma|*.wav;*.mp3;*.ogg;*.wma|*.*|*.*")
        if path:
            self._sound.SetValue(path)

    def _onTest(self, evt):
        _play_alert(self.getSettings())

class WordEditDialog(wx.Dialog):
    """Add or edit one word, with all of its settings in the same place."""
    def __init__(self, parent, category, word=None):
        super().__init__(parent, title=_("Edit Word") if word else _("Add Word"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        word = word or {"text": "", "enabled": True, "inherit": True}
        pnl = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(wx.StaticText(pnl, label=_("Word or phrase:")), 0, wx.ALL, 4)
        self._text = wx.TextCtrl(pnl, value=word.get("text", ""))
        box.Add(self._text, 0, wx.EXPAND | wx.ALL, 4)

        self._enabled = wx.CheckBox(pnl, label=_("Enable this word"))
        self._enabled.SetValue(bool(word.get("enabled", True)))
        box.Add(self._enabled, 0, wx.ALL, 4)

        self._inherit = wx.CheckBox(pnl, label=_("Use the settings of the category"))
        self._inherit.SetValue(bool(word.get("inherit", True)))
        self._inherit.Bind(wx.EVT_CHECKBOX, self._onInherit)
        box.Add(self._inherit, 0, wx.ALL, 4)

        self._settings = WordSettingsPanel(pnl, _word_settings(category, word))
        box.Add(self._settings, 1, wx.EXPAND | wx.ALL, 4)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(pnl, wx.ID_OK, _("OK")); cancel = wx.Button(pnl, wx.ID_CANCEL, _("Cancel"))
        buttons.AddButton(ok); buttons.AddButton(cancel); buttons.Realize()
        box.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 6)

        pnl.SetSizer(box)
        outer = wx.BoxSizer(wx.VERTICAL); outer.Add(pnl, 1, wx.EXPAND); self.SetSizer(outer)
        _name_controls(self)
        self.SetSize((520, 640)); self.CenterOnScreen()
        self._onInherit(None)
        self._text.SetFocus()

    def _onInherit(self, evt):
        self._settings.enableAll(not self._inherit.GetValue())

    def getWord(self):
        word = {"text": self._text.GetValue().strip(),
                "enabled": self._enabled.GetValue(),
                "inherit": self._inherit.GetValue()}
        word.update(self._settings.getSettings())
        return word

class CategoryEditDialog(wx.Dialog):
    """Add or edit a category, including the settings its new words start from."""
    def __init__(self, parent, category=None):
        super().__init__(parent, title=_("Edit category...") if category else _("Add category..."),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        category = category or {"name": "", "enabled": True}
        pnl = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(wx.StaticText(pnl, label=_("Category name:")), 0, wx.ALL, 4)
        self._name = wx.TextCtrl(pnl, value=category.get("name", ""))
        box.Add(self._name, 0, wx.EXPAND | wx.ALL, 4)

        self._enabled = wx.CheckBox(pnl, label=_("Enable this category"))
        self._enabled.SetValue(bool(category.get("enabled", True)))
        box.Add(self._enabled, 0, wx.ALL, 4)

        box.Add(wx.StaticText(pnl, label=_("Default settings for words added to this category")), 0, wx.ALL, 4)
        self._settings = WordSettingsPanel(pnl, category)
        box.Add(self._settings, 1, wx.EXPAND | wx.ALL, 4)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(pnl, wx.ID_OK, _("OK")); cancel = wx.Button(pnl, wx.ID_CANCEL, _("Cancel"))
        buttons.AddButton(ok); buttons.AddButton(cancel); buttons.Realize()
        box.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 6)

        pnl.SetSizer(box)
        outer = wx.BoxSizer(wx.VERTICAL); outer.Add(pnl, 1, wx.EXPAND); self.SetSizer(outer)
        _name_controls(self)
        self.SetSize((520, 620)); self.CenterOnScreen()
        self._name.SetFocus()

    def getCategory(self):
        category = {"name": self._name.GetValue().strip(),
                    "enabled": self._enabled.GetValue()}
        category.update(self._settings.getSettings())
        return category

# ── Word List Dialog ───────────────────────────────────────────────

class WordListDialog(wx.Dialog):
    def __init__(self, parent, categories=None):
        super().__init__(parent, title=_("Manage words..."), size=(820, 600),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.categories = _normalize_word_categories(
            categories if categories is not None else _get_word_categories())
        pnl = wx.Panel(self)
        root = wx.BoxSizer(wx.HORIZONTAL)

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(pnl, label=_("Categories")), 0, wx.ALL, 4)
        self.catList = wx.ListBox(pnl, style=wx.LB_SINGLE)
        left.Add(self.catList, 1, wx.EXPAND | wx.ALL, 4)
        for label, handler in ((_("Add category..."), self._addCategory),
                               (_("Edit category..."), self._editCategory),
                               (_("Remove category"), self._removeCategory)):
            button = wx.Button(pnl, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            left.Add(button, 0, wx.EXPAND | wx.ALL, 2)

        right = wx.BoxSizer(wx.VERTICAL)
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(wx.StaticText(pnl, label=_("Search:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.search = wx.TextCtrl(pnl)
        self.search.Bind(wx.EVT_TEXT, self._onSearch)
        search_row.Add(self.search, 1, wx.ALL, 4)
        right.Add(search_row, 0, wx.EXPAND)
        self.wordList = wx.ListBox(pnl, style=wx.LB_SINGLE)
        self.wordList.Bind(wx.EVT_LISTBOX_DCLICK, self._editWord)
        right.Add(self.wordList, 1, wx.EXPAND | wx.ALL, 4)
        wordButtons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("Add"), self._addWord), (_("Edit"), self._editWord),
                               (_("Remove"), self._removeWord)):
            button = wx.Button(pnl, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            wordButtons.Add(button, 0, wx.RIGHT, 3)
        right.Add(wordButtons, 0, wx.ALL, 4)
        ioButtons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("Import from file..."), self._importFile),
                               (_("Import from clipboard"), self._importClipboard),
                               (_("Export to file..."), self._exportFile)):
            button = wx.Button(pnl, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            ioButtons.Add(button, 0, wx.RIGHT, 3)
        right.Add(ioButtons, 0, wx.ALL, 4)

        root.Add(left, 1, wx.EXPAND)
        root.Add(right, 2, wx.EXPAND)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(root, 1, wx.EXPAND | wx.ALL, 6)
        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(pnl, wx.ID_OK, _("OK")); cancel = wx.Button(pnl, wx.ID_CANCEL, _("Cancel"))
        buttons.AddButton(ok); buttons.AddButton(cancel); buttons.Realize()
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        pnl.SetSizer(outer)
        self.catList.Bind(wx.EVT_LISTBOX, self._onCategory)
        self._refreshCategories()
        _name_controls(self)
        self.CenterOnScreen()
        self.catList.SetFocus()

    # ── lists ──────────────────────────────────────────────────────────
    def _currentCategory(self):
        index = self.catList.GetSelection()
        return self.categories[index] if index != wx.NOT_FOUND else None

    def _shownWords(self):
        """The words of the category that match the search box."""
        category = self._currentCategory()
        if not category:
            return []
        query = self.search.GetValue().strip().casefold()
        if not query:
            return list(category["words"])
        return [word for word in category["words"] if query in word["text"].casefold()]

    def _currentWord(self):
        words = self._shownWords()
        index = self.wordList.GetSelection()
        if index == wx.NOT_FOUND or index >= len(words):
            return None
        return words[index]

    def _onSearch(self, evt):
        self._refreshWords(0)

    def _refreshCategories(self, select=None):
        selection = self.catList.GetSelection() if select is None else select
        self.catList.Clear()
        for category in self.categories:
            label = "{} ({})".format(category["name"], len(category["words"]))
            if not category.get("enabled", True):
                label = "[off] " + label
            self.catList.Append(label)
        if self.categories:
            if selection == wx.NOT_FOUND or selection is None or selection >= len(self.categories):
                selection = 0
            self.catList.SetSelection(selection)
        self._refreshWords()

    def _refreshWords(self, select=None):
        selection = self.wordList.GetSelection() if select is None else select
        self.wordList.Clear()
        words = self._shownWords()
        counts = _get_word_counts()
        for word in words:
            label = word["text"]
            if not word.get("enabled", True):
                label = "[off] " + label
            if not word.get("inherit", True):
                label += "  *"
            heard = counts.get(word["text"], 0)
            if heard:
                label += "  " + _("heard {n} times").format(n=heard)
            self.wordList.Append(label)
        if words:
            if selection is None or selection == wx.NOT_FOUND or selection >= len(words):
                selection = 0
            self.wordList.SetSelection(selection)

    def _onCategory(self, evt):
        self._refreshWords(0)

    # ── categories ──────────────────────────────────────────────────────
    def _addCategory(self, evt):
        dlg = CategoryEditDialog(self)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                category = dlg.getCategory()
                if not category["name"]:
                    return
                category["words"] = []
                self.categories.append(category)
                self.categories = _normalize_word_categories(self.categories)
                self._refreshCategories(len(self.categories) - 1)
        finally:
            dlg.Destroy()

    def _editCategory(self, evt):
        category = self._currentCategory()
        if not category:
            return
        index = self.catList.GetSelection()
        dlg = CategoryEditDialog(self, category)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                updated = dlg.getCategory()
                if updated["name"]:
                    category.update(updated)
                    self.categories = _normalize_word_categories(self.categories)
                    self._refreshCategories(index)
        finally:
            dlg.Destroy()

    def _removeCategory(self, evt):
        index = self.catList.GetSelection()
        if index == wx.NOT_FOUND or len(self.categories) <= 1:
            return
        self.categories.pop(index)
        self._refreshCategories(max(0, index - 1))

    # ── words ──────────────────────────────────────────────────────────
    def _addWord(self, evt):
        category = self._currentCategory()
        if not category:
            return
        dlg = WordEditDialog(self, category)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            word = dlg.getWord()
        finally:
            dlg.Destroy()
        if not word["text"]:
            return
        if any(w["text"].casefold() == word["text"].casefold() for w in category["words"]):
            gui.messageBox(_("This word is already in the category."), "SuperTools", wx.OK | wx.ICON_INFORMATION, self)
            return
        category["words"].append(word)
        self._refreshCategories(self.catList.GetSelection())
        self._refreshWords(len(category["words"]) - 1)

    def _editWord(self, evt):
        category = self._currentCategory()
        word = self._currentWord()
        if not category or not word:
            return
        index = self.wordList.GetSelection()
        del index
        dlg = WordEditDialog(self, category, word)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            updated = dlg.getWord()
        finally:
            dlg.Destroy()
        if updated["text"]:
            word.clear()
            word.update(updated)
            self._refreshWords()

    def _removeWord(self, evt):
        category = self._currentCategory()
        word = self._currentWord()
        if not category or not word:
            return
        index = self.wordList.GetSelection()
        category["words"].remove(word)
        self._refreshCategories(self.catList.GetSelection())
        self._refreshWords(max(0, index - 1))

    # ── import and export ────────────────────────────────────────────────
    def _addWords(self, texts):
        """Add words that are not in the category yet; they follow its settings."""
        category = self._currentCategory()
        if not category:
            return
        existing = {w["text"].casefold() for w in category["words"]}
        added = 0
        for text in texts:
            text = text.strip()
            if not text or text.casefold() in existing:
                continue
            existing.add(text.casefold())
            category["words"].append({"text": text, "enabled": True, "inherit": True})
            added += 1
        if added:
            self.categories = _normalize_word_categories(self.categories)
            self._refreshCategories(self.catList.GetSelection())
            ui.message(_("{n} words added.").format(n=added))
        else:
            ui.message(_("No new words were found."))

    def _importFile(self, evt):
        path = _ask_for_file(self, _("Import from file..."),
                             wildcard="*.txt;*.json|*.txt;*.json|*.*|*.*")
        if not path:
            return
        content = _run_file_task(self, _read_text_file, path)
        if content is not None:
            self._addWords(_split_word_list(content))

    def _importClipboard(self, evt):
        try:
            text = api.getClipData()
        except Exception:
            text = ""
        self._addWords(_split_word_list(text or ""))

    def _exportFile(self, evt):
        category = self._currentCategory()
        if not category:
            return
        path = _ask_for_file(self, _("Export to file..."), save=True,
                             default=category["name"] + ".txt", wildcard="*.txt|*.txt")
        if path:
            _run_file_task(self, _write_text_file, path,
                           "\n".join(word["text"] for word in category["words"]))

    def getCategories(self):
        return self.categories

def _split_word_list(content):
    """Words from a text or JSON file: one per line, or separated by commas."""
    content = content.strip()
    if content.startswith("[") or content.startswith("{"):
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                data = data.get("words", [])
            if isinstance(data, list):
                return [str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in data]
        except Exception:
            pass
    words = []
    for line in content.splitlines():
        parts = line.split(",") if "," in line else [line]
        words.extend(part.strip() for part in parts)
    return words

# ── Process Manager Dialog ─────────────────────────────────────────────

class ProcessManagerDialog(wx.Dialog):
    """
    Name, PID and memory in three columns, a filter that also takes a PID, and
    one row of actions. Everything is reachable from the keyboard, and the list
    keeps the process it was on when it refreshes.
    """
    def __init__(self, parent):
        super().__init__(parent, title=_("Process Manager"), size=(760, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._rows = []
        self._shown = []
        # CPU and publisher cost time to collect, so they are gathered only when
        # the user asks for them.
        self._details = _cfg_get_bool("pm_details", False)
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)

        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_row.Add(wx.StaticText(panel, label=_("Filter processes:")),
                       0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._filter = wx.TextCtrl(panel)
        self._filter.Bind(wx.EVT_TEXT, self._onFilter)
        filter_row.Add(self._filter, 1)
        filter_row.Add(wx.StaticText(panel, label=_("Sort the list by:")),
                       0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        self._sort = wx.Choice(panel, choices=[_("Name"), _("Memory use"), _("CPU"), _("PID")])
        saved_sort = _cfg_get_str("pm_sort", PM_SORT_KEYS[0])
        self._sort.SetSelection(PM_SORT_KEYS.index(saved_sort) if saved_sort in PM_SORT_KEYS else 0)
        self._sort.Bind(wx.EVT_CHOICE, self._onSort)
        filter_row.Add(self._sort, 0)
        self._detailsBox = wx.CheckBox(panel, label=_("Show CPU and publisher"))
        self._detailsBox.SetValue(self._details)
        self._detailsBox.Bind(wx.EVT_CHECKBOX, self._onDetails)
        filter_row.Add(self._detailsBox, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        box.Add(filter_row, 0, wx.EXPAND | wx.ALL, 6)
        box.Add(wx.StaticText(panel, label=_("Type a name, or a number to find a PID.")),
                0, wx.LEFT | wx.BOTTOM, 6)

        self._list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate(((_("Name"), 200), (_("PID"), 80),
                                                (_("Memory use"), 110), (_("CPU"), 70),
                                                (_("Publisher"), 180))):
            self._list.InsertColumn(index, label, width=width)
        self._list.Bind(wx.EVT_LIST_COL_CLICK, self._onColumnClick)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onProperties)
        box.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        self._status = wx.StaticText(panel, label="")
        box.Add(self._status, 0, wx.ALL, 6)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("&Refresh list"), self._onRefresh),
                               (_("&End process"), self._onKill),
                               (_("Re&start process"), self._onRestart),
                               (_("End &all filtered"), self._onKillAll),
                               (_("Restart all &filtered"), self._onRestartAll)):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 3)
        box.Add(actions, 0, wx.LEFT | wx.RIGHT, 6)

        more = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("&Open file location"), self._onLocation),
                               (_("&Copy details"), self._onCopyDetails),
                               (_("&Properties"), self._onProperties)):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            more.Add(button, 0, wx.RIGHT, 3)
        more.Add(wx.StaticText(panel, label=_("Priority:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        self._priority = wx.Choice(panel, choices=[_("Low"), _("Below normal"), _("Normal"),
                                                   _("Above normal"), _("High")])
        self._priority.SetSelection(2)
        self._priority.Bind(wx.EVT_CHOICE, self._onPriority)
        more.Add(self._priority, 0, wx.LEFT, 4)
        close = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        more.Add(close, 0, wx.LEFT, 8)
        box.Add(more, 0, wx.ALL, 6)

        panel.SetSizer(box)
        outer = wx.BoxSizer(wx.VERTICAL); outer.Add(panel, 1, wx.EXPAND); self.SetSizer(outer)
        self.SetEscapeId(wx.ID_CLOSE)
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._onTimer, self._timer)
        self.Bind(wx.EVT_CLOSE, self._onClose)
        self._refresh(select_explorer=True)
        self._startAutoRefresh()
        _name_controls(self)
        self.CenterOnScreen()
        self._filter.SetFocus()

    # ── the list ───────────────────────────────────────────────────────
    def _refresh(self, select_explorer=False):
        if not self or not self._list:
            return
        keep = None if select_explorer else self.selected()
        self._rows = _sort_process_rows(_get_process_rows(self._details), self._sortKey())
        self._fill()
        if select_explorer:
            self._select(next((row[0] for row in self._shown
                               if row[1].lower() == "explorer.exe"), None))
        elif keep:
            self._select(keep[0])

    def _fill(self):
        self._shown = _filter_process_rows(self._rows, self._filter.GetValue())
        self._list.DeleteAllItems()
        for index, (pid, name, memory, cpu, publisher) in enumerate(self._shown):
            self._list.InsertItem(index, name)
            self._list.SetItem(index, 1, str(pid))
            self._list.SetItem(index, 2, "{:.1f} MB".format(memory / 1024.0 / 1024.0))
            self._list.SetItem(index, 3, "{:.0f}%".format(cpu) if self._details else "")
            self._list.SetItem(index, 4, publisher)
        self._status.SetLabel(_("{shown} of {total} processes").format(
            shown=len(self._shown), total=len(self._rows)))
        if self._shown and self._list.GetFirstSelected() == -1:
            self._select(self._shown[0][0])

    def _select(self, pid):
        for index, row in enumerate(self._shown):
            if row[0] == pid:
                self._list.Select(index)
                self._list.Focus(index)
                self._list.EnsureVisible(index)
                return True
        return False

    def selected(self):
        """The row the list is on, or None after telling the user there is none."""
        index = self._list.GetFirstSelected()
        if index == -1 or index >= len(self._shown):
            ui.message(_("No process selected."))
            return None
        return self._shown[index]

    def _sortKey(self):
        return PM_SORT_KEYS[max(0, self._sort.GetSelection())]

    def _onSort(self, evt):
        _cfg_set("pm_sort", self._sortKey())
        self._refresh()

    def _onDetails(self, evt):
        self._details = self._detailsBox.GetValue()
        _cfg_set("pm_details", self._details)
        self._refresh()

    def _onColumnClick(self, evt):
        # The columns are in the same order as the ways of sorting.
        self._sort.SetSelection(min(evt.GetColumn(), len(PM_SORT_KEYS) - 1))
        self._onSort(None)

    def _onFilter(self, evt):
        self._fill()

    def _onRefresh(self, evt):
        self._refresh()

    # ── automatic refresh ────────────────────────────────────────────────
    def _startAutoRefresh(self):
        if not _cfg_get_bool("pm_autorefresh_enabled", False):
            return
        try:
            self._timer.Start(max(1, _cfg_get_int("pm_autorefresh_seconds", 5)) * 1000)
        except Exception:
            log.debugWarning("SuperTools: auto refresh failed to start", exc_info=True)

    def _onTimer(self, evt):
        self._refresh()

    def _onClose(self, evt):
        try:
            self._timer.Stop()
        except Exception:
            pass
        evt.Skip()

    # ── actions ──────────────────────────────────────────────────────
    def _filtered(self):
        """The processes a bulk action would hit, once the user agrees to it."""
        if not self._filter.GetValue().strip():
            ui.message(_("Type a name in the filter first: this would hit every process."))
            return None
        if not self._shown:
            ui.message(_("No process matches the filter."))
            return None
        if _cfg_get_bool("pm_confirm_bulk", True):
            question = _("This affects {n} processes. Continue?").format(n=len(self._shown))
            if gui.messageBox(question, "SuperTools", wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
                return None
        return list(self._shown)

    def _work(self, function, rows, message):
        """Run a slow action off the GUI thread and refresh when it is done."""
        pids = [row[0] for row in rows]
        def run():
            done = sum(1 for pid in pids if function(pid))
            ui.message(message.format(n=done))
            wx.CallAfter(self._refresh)
        threading.Thread(target=run, daemon=True).start()

    def _onKill(self, evt):
        row = self.selected()
        if row:
            self._work(_kill_process, [row], _("Process {name} killed.").format(name=row[1]))

    def _onKillAll(self, evt):
        rows = self._filtered()
        if rows:
            self._work(_kill_process, rows, _("{n} processes ended."))

    def _onRestart(self, evt):
        row = self.selected()
        if row:
            self._work(_restart_one, [row], _("Process {name} restarted.").format(name=row[1]))

    def _onRestartAll(self, evt):
        rows = self._filtered()
        if rows:
            self._work(_restart_one, rows, _("{n} processes restarted."))

    def _onLocation(self, evt):
        row = self.selected()
        if row and not _open_process_location(row[0]):
            ui.message(_("The location of this program is unknown."))

    def _onCopyDetails(self, evt):
        row = self.selected()
        if not row:
            return
        info = _process_info(row[0])
        details = _("Name: {name}\nPID: {pid}\nProgram: {exe}\nPublisher: {publisher}\nMemory: {memory:.1f} MB\nState: {status}").format(
            name=info.get("name") or row[1], pid=row[0], exe=info.get("exe") or "?",
            publisher=_publisher(info.get("exe")) or "?",
            memory=info.get("memory", 0) / 1024.0 / 1024.0, status=info.get("status", "?"))
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(details))
            wx.TheClipboard.Close()
            ui.message(_("Process details copied."))

    def _onProperties(self, evt):
        row = self.selected()
        if not row:
            return
        exe = _process_info(row[0]).get("exe")
        if not exe or not os.path.exists(exe):
            ui.message(_("The location of this program is unknown."))
            return
        if not _launch_detached(["rundll32.exe", "shell32.dll,ShellExec_RunDLL", exe]):
            ui.message(_("The properties window could not be opened."))

    def _onPriority(self, evt):
        row = self.selected()
        if not row:
            return
        if _set_process_priority(row[0], PM_PRIORITY_KEYS[max(0, self._priority.GetSelection())]):
            ui.message(_("Priority changed."))
        else:
            ui.message(_("The priority could not be changed. Administrator rights may be needed."))

# ── Help Dialog ───────────────────────────────────────────────────────────────

HELP_TEXT = """\
SuperTools for NVDA v{ver}
===========================

COMMAND MODE
  Press NVDA+Shift+U, then press one key.
  H        Help
  X        Changes
  C        Convert the selected text
  Shift+C  Convert the word before the cursor, without selecting it
  Z        Undo the last conversion
  S        Settings
  W        Word Monitor manager
  Shift+W  Turn the Word Monitor on or off
  P        Process Manager
  L        Lock or unlock the keyboard
  T        Check whether the clock is right
  U        Look for a new version
  Escape   Leave command mode

NVDA+Shift+U is the only shortcut this add-on uses; everything else is reached
from command mode or from the settings dialog.

While command mode is on, nothing reaches the application you are working in.
A key that is not a command only plays a short beep and command mode stays on.
Modifier keys (Shift, Control, Alt, the NVDA key) are not commands either.
Commands are recognised by the physical key, so they work on Persian and other
non-Latin layouts. If no key is pressed at all, command mode ends by itself;
the waiting time can be changed or switched off in the settings.

Each command has its own beep sequence, so you can tell by ear which command
ran. The sequences can be changed in Settings, General tab.

LAYOUT FIXER
  Works with every keyboard layout Windows has, not a chosen pair. The text
  itself says which layout it was typed with, and C moves it to the next one;
  press C again to carry on to the one after that, all the way round. With two
  layouts installed that is simply "the other one", and nothing has to be set
  at all.
  C converts the selection, Shift+C the word just typed, Z puts back what was
  there before the last conversion.
  A layout can be left out of the ring in the settings, and SuperTools can say
  which layout the text landed in.
  The clipboard is used to replace the text; by default its previous content is
  put back afterwards, and the converted text is spoken. Both are optional.
  Optionally SuperTools can also watch what you type and tell you when a word
  looks like it was typed with the wrong layout: a Latin word without a single
  vowel, such as "sghl". It can warn with a short sound or convert the word
  straight away.

WORD MONITOR
  Words are kept in categories. A category holds the settings that words added
  to it start from, and every word can keep those or use its own.
  Per word or per category you can choose:
    - matching anywhere in the text or whole words only, and whether upper and
      lower case must match;
    - what happens when the word is spoken: beeps only, extra text only, both,
      or not speaking the word at all;
    - the text said before the word;
    - the beeps: how many, how high, how long each one lasts, the gap between
      them, or a sequence of your own, and whether speech is interrupted;
    - a wav file to play instead of the beeps.
  The word list has a search box and shows how often each word has been heard.
  Words can be imported from a text or JSON file or from the clipboard, and
  exported to a file.

APPLICATIONS
  Every feature can be limited to some applications or kept out of them, on its
  own settings tab: for example the Word Monitor only in your chat program.
  The programs are ticked off a list of what is running, so nothing has to be
  typed or spelled correctly.

PROCESS MANAGER
  A list of name, PID and memory use, with processor use and the publisher of
  the program as two more columns that can be switched on when wanted. Type in the filter to narrow it down, or
  type a number to find a PID. Sort by clicking a column header or with the
  sort box. The list can refresh itself every few seconds and always refreshes
  right after an action, keeping the process you were on.
  End or restart the selected process, or every process the filter shows, open
  the file location, copy the details, open the properties window and change
  the priority.
  The two actions that hit every filtered process need a non-empty filter and
  ask first, so nothing can run over the whole machine by accident.
  Restarted processes are started detached from NVDA and keep running when NVDA
  restarts or exits.

KEYBOARD LOCK
  L locks the keyboard, and L locks it again to let it go. While it is locked
  every key is swallowed before it reaches anything at all, NVDA included, so
  a cat on the desk or a child at the keyboard changes nothing. The one key
  that still works is the one that opens command mode, so NVDA+Shift+U and
  then L always unlocks it. If you have bound command mode to some other key,
  that key is the one that works.

  A lock is never written down anywhere: quitting or restarting NVDA ends it,
  which is the last way out if anything ever goes wrong. The lock can be
  switched off altogether in Settings, General tab.

THE CLOCK
  T says how far the computer's clock is from the real time, and offers to put
  it right. A clock that is wrong is worth finding, because secure connections
  stop working when it is: certificates look expired or not yet valid, and the
  error you get says nothing about the time.

  The time is read from the Date header that any web server sends back, so no
  service has to be signed up for and nothing about you is sent. When the
  clock is badly wrong, https itself fails, so a plain http address is tried
  as well - for that one header and nothing else.

  Two ways to fix it are offered. The first asks the Windows time service to
  do what it is for, which is the right answer almost always. The second sets
  the clock straight from the time the web server gave, for networks where the
  time service cannot reach its own servers. Windows asks for permission
  before either one; if you say no, nothing happens.

THE FIRST RUN
  The first time SuperTools starts it asks three things: which of its tools you
  want, which keyboard layouts you use, and how it should sound.
  Everything it asks can be changed later, and the same questions can be asked
  again from Settings, General tab.

UPDATES
  U in command mode asks whether a newer version exists and tells you.
  Settings, General tab can also do it after NVDA starts. It is off until you
  turn it on, it waits until NVDA has finished starting so that starting is
  never held up by it, and it then asks at most once a day.

  When there is something newer you are shown what changed and asked what you
  want: update now, open the download page, be reminded later, or skip that
  version. Updating now fetches the file and hands it to NVDA, which asks its
  own question before installing anything, exactly as it would for a file you
  had downloaded yourself. A version you skip is never brought up again by
  itself; Settings, General tab can undo that.

  If you installed SuperTools from NVDA's Add-on Store, the store already
  keeps it up to date and this can stay off.

SETTINGS
  Every feature can be switched off on its own tab. All settings can be
  exported to a file and imported again on another machine, and a weekly backup
  is kept automatically in the NVDA configuration folder.

SOUNDS
  Every sound the add-on makes can come from a theme: for each sound
  separately, either beeps or a sound file. wav plays through NVDA's own audio;
  mp3 and the other formats Windows can decode work as well. Whatever a theme
  does not mention keeps the built-in beep, so a theme can be as small as one
  sound.
  Settings, General tab, Sounds: choose a theme, hear it, build one of your own
  sound by sound with the wizard, open the folder they live in, or save a
  template to write by hand. Themes written by other people
  go in that folder and appear in the list, with their author's name beside
  them.

LANGUAGES
  SuperTools speaks the language NVDA itself is set to, through NVDA's own
  translation system. It comes with English, Persian, Arabic, German, Spanish,
  French, Italian, Portuguese, Russian, Turkish and Simplified Chinese.
  The help you are reading is translated too: it is doc/<language>/help.txt,
  plain text, and the documentation NVDA shows is built from it.
  A language can be written from inside the add-on: Settings, General tab,
  Language, "Create or continue a translation". It saves the same file a
  translator would send, and can show you your own language straight away.
  You can also translate locale/nvda.pot with a tool such as Poedit, save it
  as locale/<language>/LC_MESSAGES/nvda.po and send it to the author. Put
  your name in the Last-Translator field and it appears in the settings, beside
  the language you translated.

WHO MADE THIS
  SuperTools is written by Abolfazl Abaspoor, with the help of an AI assistant.
  The first translations were made by that assistant and have not been reviewed
  by native speakers: corrections are welcome and are credited. A language can
  be the work of several people, and every one of them is named, in the settings
  and in TRANSLATORS.md. Sound themes carry their author's name in the same way.

CHANGES
  Changes is shown automatically only once for each SuperTools version.
""".format(ver=CURRENT_VERSION)

# ── What the add-on is, and what changed ─────────────────────────────────
# INTRO opens the screen every time. VERSION_NOTES is the history: a reader
# only ever sees the entries newer than the version they had, so someone who
# goes from 1.0 to 1.3 in one step still learns what happened in 1.1 and 1.2.

INTRO_TEXT = """\
SuperTools {ver}

A toolbox for NVDA that keeps growing. Everything it can do is reached from one
command mode, so the add-on takes a single shortcut no matter how much is added
to it later.

Press NVDA+Shift+U, then one key:

  H        Help, with every feature explained
  X        This screen
  C        Convert the selected text between two keyboard layouts
  Shift+C  Convert the word before the cursor, without selecting it
  Z        Undo the last conversion
  W        Word Monitor: words that get their own sound when spoken
  Shift+W  Turn the Word Monitor on or off
  P        Process Manager
  L        Lock or unlock the keyboard
  T        Check whether the clock is right
  U        Look for a new version
  S        Settings
  Escape   Leave command mode

While command mode is on, nothing is typed into the program you are working in.
A key that is not a command only plays a short beep and you stay in command
mode, so you can simply press the right key.
"""

# Newest first. Each entry is what changed in that version.
VERSION_NOTES = [
    ("1.0.0", """\nThe first public release.

Everything above is new, because this is the first version anyone outside
has seen. Later releases will list here only what changed since the version
you had, so you never read the same news twice."""),
]

def _version_tuple(version):
    """"1.10.2" -> (1, 10, 2), so versions sort the way people read them."""
    parts = []
    for piece in str(version).split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))[:3]

def _notes_since(version):
    """The history entries newer than the version the user had."""
    if not version:
        return []
    known = _version_tuple(version)
    return [(number, text) for number, text in VERSION_NOTES
            if _version_tuple(number) > known]

def _changes_text(since=None, everything=False):
    """
    The text of the Changes screen: what the add-on is, then what is new.
    A fresh installation only gets the introduction, because nothing is new to
    someone who has never had it.
    """
    parts = [INTRO_TEXT.format(ver=CURRENT_VERSION)]
    notes = VERSION_NOTES if everything else _notes_since(since)
    if notes:
        parts.append(_("What is new since the version you had:")
                     if not everything else _("What changed in each version:"))
        for number, text in notes:
            parts.append("SuperTools {}\n{}".format(number, text))
    return "\n\n".join(parts)

class ChangesDialog(wx.Dialog):
    """The welcome and history screen. Read-only text, keyboard friendly."""
    def __init__(self, parent, text):
        super().__init__(parent, title="SuperTools", size=(560, 460),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)
        body = wx.TextCtrl(panel, value=text,
                           style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        box.Add(body, 1, wx.EXPAND | wx.ALL, 10)
        close = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        box.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        panel.SetSizer(box)
        outer = wx.BoxSizer(wx.VERTICAL); outer.Add(panel, 1, wx.EXPAND); self.SetSizer(outer)
        self.SetEscapeId(wx.ID_CLOSE)
        _name_controls(self)
        self.CenterOnScreen()
        body.SetFocus()

def _help_text():
    """
    The help in the language NVDA is set to.

    Translated help lives in doc/<language>/help.txt, next to the documentation
    built from it, so a translator writes prose rather than two hundred separate
    lines. English is used when a language has none.
    """
    code = _cfg_get_str("language_override", "") or _nvda_language()
    for name in (code, code.split("_")[0]):
        path = os.path.join(_addon_dir(), "doc", name, "help.txt")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().replace("{ver}", CURRENT_VERSION)
        except OSError:
            continue
        except Exception:
            log.debugWarning("SuperTools: unusable help file {}".format(path), exc_info=True)
    return HELP_TEXT

class HelpDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="SuperTools - Help", size=(520, 400))
        pnl  = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        txt  = wx.TextCtrl(pnl, value=_help_text(),
                           style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        txt.SetFont(wx.Font(10, wx.FONTFAMILY_TELETYPE,
                            wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        vbox.Add(txt, 1, wx.EXPAND | wx.ALL, 10)
        btn = wx.Button(pnl, wx.ID_CLOSE, _("Close"))
        btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        vbox.Add(btn, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        pnl.SetSizer(vbox)
        _name_controls(self)
        self.CenterOnScreen()
        txt.SetFocus()

# ── Plugin ────────────────────────────────────────────────────────────────────

class UpdateDialog(wx.Dialog):
    """
    What is new, and what the user wants done about it.

    A new version is an offer, never an event that happens to you: nothing is
    downloaded until this screen is answered, and "Skip this version" is
    remembered so the same news is not brought up every day.
    """
    UPDATE, PAGE, LATER, SKIP = wx.ID_OK, wx.ID_APPLY, wx.ID_CANCEL, wx.ID_IGNORE

    def __init__(self, parent, release):
        super().__init__(parent, title="SuperTools", size=(560, 420),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._release = release
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)

        heading = _("SuperTools {version} is available. You have {current}.").format(
            version=release["version"], current=CURRENT_VERSION)
        box.Add(wx.StaticText(panel, label=heading), 0, wx.ALL, 10)

        box.Add(wx.StaticText(panel, label=_("What is new:")), 0, wx.LEFT | wx.TOP, 10)
        notes = wx.TextCtrl(panel, value=release["notes"] or _("No notes were written."),
                            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        notes.SetName(_("What is new"))
        box.Add(notes, 1, wx.EXPAND | wx.ALL, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        if release.get("download"):
            update = wx.Button(panel, self.UPDATE, _("&Update now"))
            update.SetDefault()
            buttons.Add(update, 0, wx.ALL, 4)
        buttons.Add(wx.Button(panel, self.PAGE, _("Open the &download page")), 0, wx.ALL, 4)
        buttons.Add(wx.Button(panel, self.LATER, _("Remind me &later")), 0, wx.ALL, 4)
        buttons.Add(wx.Button(panel, self.SKIP, _("&Skip this version")), 0, wx.ALL, 4)
        box.Add(buttons, 0, wx.ALIGN_CENTER | wx.ALL, 6)

        for identifier in (self.UPDATE, self.PAGE, self.LATER, self.SKIP):
            button = panel.FindWindow(identifier)
            if button:
                button.Bind(wx.EVT_BUTTON,
                            lambda evt, which=identifier: self.EndModal(which))
        panel.SetSizer(box)
        self.Bind(wx.EVT_CHAR_HOOK, self._onKey)
        self.CentreOnScreen()
        notes.SetFocus()

    def _onKey(self, evt):
        if evt.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(self.LATER)
        else:
            evt.Skip()

class ClockDialog(wx.Dialog):
    """
    How far the computer's clock is out, and two ways to put it right.

    Neither way runs without Windows asking for permission first, and the
    difference is measured again afterwards so the answer is what happened,
    not what was attempted.
    """
    def __init__(self, parent):
        super().__init__(parent, title=_("SuperTools - Clock"), size=(520, 300),
                         style=wx.DEFAULT_DIALOG_STYLE)
        self._server = None
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(wx.StaticText(panel, label=_(
            "A clock that is wrong stops secure connections from working, and the "
            "error never mentions the time.")), 0, wx.ALL, 10)
        self._status = wx.TextCtrl(panel, value=_("Asking a web server for the time..."),
                                   style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self._status.SetName(_("What the clock says"))
        box.Add(self._status, 1, wx.EXPAND | wx.ALL, 10)

        self._windows = wx.Button(panel, label=_("Let &Windows fix it"))
        self._windows.Bind(wx.EVT_BUTTON, self._onWindows)
        self._internet = wx.Button(panel, label=_("Set it from the &internet"))
        self._internet.Bind(wx.EVT_BUTTON, self._onInternet)
        self._again = wx.Button(panel, label=_("Check &again"))
        self._again.Bind(wx.EVT_BUTTON, lambda evt: self._measure())
        close = wx.Button(panel, wx.ID_CANCEL, _("&Close"))

        row = wx.BoxSizer(wx.HORIZONTAL)
        for button in (self._windows, self._internet, self._again, close):
            row.Add(button, 0, wx.ALL, 4)
        box.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
        panel.SetSizer(box)
        self.CentreOnScreen()
        self._busy(True)
        wx.CallAfter(self._measure)

    def _busy(self, busy):
        for button in (self._windows, self._internet, self._again):
            button.Enable(not busy)

    def _say(self, text, speak=True):
        self._status.SetValue(text)
        if speak:
            ui.message(text)

    def _measure(self):
        self._busy(True)
        self._say(_("Asking a web server for the time..."), speak=False)
        def run():
            try:
                drift, host = _clock_drift()
                wx.CallAfter(self._measured, drift, host, None)
            except Exception as ex:
                wx.CallAfter(self._measured, 0, "", ex)
        threading.Thread(target=run, daemon=True).start()

    def _measured(self, drift, host, error):
        if error is not None:
            self._server = None
            self._say(_("The time could not be read from the internet. {reason}").format(
                reason=_network_error(error)))
            self._busy(False)
            self._internet.Enable(False)
            return
        self._server = time.time() - drift
        self._say(_drift_sentence(drift, host))
        self._busy(False)

    def _fix(self, work, name):
        self._busy(True)
        self._say(_("Windows will ask for permission. {what}").format(what=name),
                  speak=False)
        def run():
            try:
                ok, output = work()
            except Exception as ex:
                log.error("SuperTools: the clock could not be set", exc_info=True)
                ok, output = False, str(ex)
            wx.CallAfter(self._fixed, ok, output)
        threading.Thread(target=run, daemon=True).start()

    def _fixed(self, ok, output):
        if not ok:
            self._say(output or _("The clock was not changed."))
            self._busy(False)
            return
        if output:
            log.debug("SuperTools: clock command said: " + output)
        self._measure()

    def _onWindows(self, evt):
        self._fix(_sync_clock_with_windows, _("Asking the Windows time service."))

    def _onInternet(self, evt):
        if self._server is None:
            self._measure()
            return
        server = self._server
        self._fix(lambda: _set_clock(server), _("Setting the clock from the internet."))

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "SuperTools"

    def __init__(self):
        global _plugin
        super().__init__()
        self._openDialogs = set()
        self._settingsOpen = False
        self._commandMode = False
        self._commandCapture = None
        self._commandTimer = None
        self._typed = ""
        self._history = []
        self._oldSpeak = speech.speech.speak if BUILD_YEAR >= 2021 else speech.speak
        if BUILD_YEAR >= 2021:
            speech.speech.speak = self._mySpeak
        else:
            speech.speak = self._mySpeak
        _plugin = self
        self._locked = False
        _apply_language_override()
        # Nothing that touches the disk or the network happens while NVDA is
        # still starting. The backup and the update check wait until the user
        # is already working, so starting NVDA is never held up by us.
        delay = max(5, _cfg_get_int("update_delay_seconds", UPDATE_START_DELAY))
        wx.CallLater(delay * 1000, self._afterStartup)
        seen = _cfg_get_str("seen_version", "")
        fresh = not _cfg_get_str("setup_done", "")
        if seen != CURRENT_VERSION:
            _cfg_set("seen_version", CURRENT_VERSION)
            # On a fresh installation the setup says all of this and asks for
            # what it needs; two screens in a row would only be in the way.
            if not fresh:
                wx.CallAfter(self._showChanges, _changes_text(since=seen))
        if fresh:
            wx.CallAfter(self._showSetup)

    def _afterStartup(self):
        """The housekeeping, once NVDA is up and nobody is waiting for it."""
        try:
            _weekly_backup()
        except Exception:
            log.debugWarning("SuperTools: the weekly backup failed", exc_info=True)
        # Only if the user asked for it, and at most once a day.
        self._checkForUpdate()

    def terminate(self):
        global _plugin
        if BUILD_YEAR >= 2021:
            speech.speech.speak = self._oldSpeak
        else:
            speech.speak = self._oldSpeak
        # A lock must never outlive the add-on that made it.
        self._locked = False
        self._stopCommandMode()
        _save_word_counts()
        _close_tone_player()
        if _plugin is self:
            _plugin = None
        super().terminate()

    def _onUpdateFound(self, release, error, announce=False):
        """What to do once the answer comes back, on the GUI thread."""
        if error is not None:
            if announce:
                gui.messageBox(_network_error(error), "SuperTools",
                               wx.OK | wx.ICON_ERROR, gui.mainFrame)
            return
        if release == NO_RELEASE:
            if announce:
                gui.messageBox(_("There is nothing published to compare with yet. You have "
                                 "version {version}.").format(version=CURRENT_VERSION),
                               "SuperTools", wx.OK, gui.mainFrame)
            return
        if not release:
            if announce:
                gui.messageBox(_("You have the newest version ({version}).").format(
                    version=CURRENT_VERSION), "SuperTools", wx.OK, gui.mainFrame)
            return
        self._offerUpdate(release)

    def _offerUpdate(self, release):
        """Show what is new and do what the user decides, and nothing else."""
        if "update" in self._openDialogs:
            return
        self._openDialogs.add("update")
        answer = UpdateDialog.LATER
        dlg = None
        try:
            gui.mainFrame.prePopup()
            dlg = UpdateDialog(gui.mainFrame, release)
            answer = dlg.ShowModal()
        except Exception:
            log.error("SuperTools: update dialog failed", exc_info=True)
        finally:
            if dlg:
                dlg.Destroy()
            try:
                gui.mainFrame.postPopup()
            except Exception:
                pass
            self._openDialogs.discard("update")
        if answer == UpdateDialog.UPDATE:
            ui.message(_("Downloading SuperTools {version}...").format(
                version=release["version"]))
            _download_release(release, self._onDownloaded)
        elif answer == UpdateDialog.PAGE:
            _open_page(release["page"])
        elif answer == UpdateDialog.SKIP:
            _cfg_set("update_skip", release["version"])
            ui.message(_("Version {version} will not be offered again.").format(
                version=release["version"]))

    def _onDownloaded(self, path, error):
        if error is not None or not path:
            gui.messageBox(_network_error(error) if error else
                           _("The new version could not be downloaded."),
                           "SuperTools", wx.OK | wx.ICON_ERROR, gui.mainFrame)
            return
        if not _install_addon(path):
            gui.messageBox(_("The file was downloaded to {path}, but NVDA could not "
                             "open it. Open it yourself to install the new version."
                             ).format(path=path), "SuperTools", wx.OK | wx.ICON_WARNING,
                           gui.mainFrame)

    def _checkNow(self):
        """U in command mode: ask about a new version and say what came back."""
        ui.message(_("Looking for a new version..."))
        self._checkForUpdate(announce=True)

    def _checkForUpdate(self, announce=False):
        _check_for_update(lambda release, error: self._onUpdateFound(release, error, announce),
                          force=announce)

    def _showSetup(self):
        """The first-run questions; also reachable from the settings."""
        self._showDialog(SetupWizard, lambda dlg: dlg.save())

    def _showHelp(self):
        self._showDialog(HelpDialog)

    def _showChanges(self, text=None):
        self._changesText = text or _changes_text(everything=True)
        if "changes" in self._openDialogs:
            return
        self._openDialogs.add("changes")
        dlg = None
        try:
            gui.mainFrame.prePopup()
            dlg = ChangesDialog(gui.mainFrame, self._changesText)
            dlg.ShowModal()
        except Exception:
            log.error("SuperTools: changes dialog failed", exc_info=True)
        finally:
            if dlg:
                dlg.Destroy()
            try:
                gui.mainFrame.postPopup()
            except Exception:
                pass
            self._openDialogs.discard("changes")

    def _mySpeak(self, sequence, *args, **kwargs):
        # This replaces NVDA's own speak(): anything unexpected in here would
        # silence NVDA completely, so every failure falls back to plain speech.
        try:
            if not _get_monitor_enabled() or not _feature_allowed_here("wm"):
                return self._oldSpeak(sequence, *args, **kwargs)
            sequence, alerts = self._applyWordMonitor(sequence)
        except Exception:
            log.error("SuperTools: word monitor failed", exc_info=True)
            return self._oldSpeak(sequence, *args, **kwargs)
        if sequence:
            self._oldSpeak(sequence, *args, **kwargs)
        for settings in alerts:
            _play_alert(settings)

    def _applyWordMonitor(self, sequence):
        """
        Work out what to speak and what to play for one utterance.
        Returns (sequence, [settings to play]).
        """
        separator = getattr(speechViewer, "SPEECH_ITEM_SEPARATOR", "  ")
        text = separator.join(x for x in sequence if isinstance(x, str))
        matches = _find_word_matches(text)
        if not matches:
            return sequence, []
        prefixes, alerts, muted = [], [], []
        for word, settings in matches:
            _count_word(word)
            action = settings["action"]
            if action in ("speak", "both") and settings["prefix"]:
                if settings["prefix"] not in prefixes:
                    prefixes.append(settings["prefix"])
            if action != "speak":
                alerts.append(settings)
            if action == "mute":
                muted.append((word, settings))
        if muted:
            sequence = self._muteWords(sequence, muted)
        if prefixes:
            sequence = list(sequence)
            spoken = " ".join(prefixes) + " "
            if sequence and isinstance(sequence[0], str):
                sequence[0] = spoken + sequence[0]
            else:
                sequence.insert(0, spoken)
        return sequence, alerts

    def _muteWords(self, sequence, muted):
        """Take the muted words out of the utterance, dropping anything left empty."""
        result = []
        for item in sequence:
            if isinstance(item, str):
                for word, settings in muted:
                    item = _mute_word(item, word, settings)
                item = re.sub(r"\s{2,}", " ", item).strip()
                if not item:
                    continue
            result.append(item)
        return result

    # ── Text helpers ───────────────────────────────────────────────────────
    # ── Watching what is typed ──────────────────────────────────────────
    def event_typedCharacter(self, obj, nextHandler, ch):
        """
        NVDA hands every typed character here. The work is a single character
        appended to a small buffer; the check only runs once a word ends.
        """
        try:
            if _cfg_get_bool("autocheck_enabled", False):
                if ch and ch.isalpha():
                    self._typed += ch
                    if len(self._typed) > 40:
                        self._typed = self._typed[-40:]
                else:
                    word, self._typed = self._typed, ""
                    if word:
                        self._checkTypedWord(word)
        except Exception:
            log.debugWarning("SuperTools: typed character check failed", exc_info=True)
        nextHandler()

    def _checkTypedWord(self, word):
        """
        Warn about a word that looks like it was typed with the wrong layout.
        A Latin word of a few letters with no vowel at all is the giveaway:
        "sghl" for "سلام". Nothing is changed unless that was asked for.
        """
        if not _feature_allowed_here("kb") or not self._isEnabled("kb"):
            return
        if len(word) < _cfg_get_int("autocheck_min_length", 3):
            return
        if not word.isascii() or any(letter in "aeiouyAEIOUY" for letter in word):
            return
        if _cfg_get_bool("autocheck_convert", False):
            wx.CallAfter(self._convertLastWord)
        else:
            _play_event("autocheck", _get_command_sound("autocheck"))

    def _getSelectedText(self):
        try:
            obj = api.getFocusObject()
            ti = obj.treeInterceptor
            if ti and ti.isReady:
                obj = ti
            info = obj.makeTextInfo(textInfos.POSITION_SELECTION)
            return info.text if info and info.text else None
        except Exception:
            return None

    def _selectWordBeforeCaret(self):
        """
        Select the word the cursor sits behind, so it can be converted without
        selecting it by hand. Falls back to control+shift+leftArrow for
        applications whose text objects cannot move their own selection.
        """
        try:
            obj = api.getFocusObject()
            ti = obj.treeInterceptor
            if ti and ti.isReady:
                obj = ti
            info = obj.makeTextInfo(textInfos.POSITION_CARET)
            info.expand(textInfos.UNIT_WORD)
            if not info.text.strip():
                # The cursor is behind a space: take the word before it.
                info.move(textInfos.UNIT_WORD, -1)
                info.expand(textInfos.UNIT_WORD)
            if info.text.strip():
                info.updateSelection()
                return True
        except Exception:
            log.debugWarning("SuperTools: could not select the previous word", exc_info=True)
        try:
            import keyboardHandler
            keyboardHandler.KeyboardInputGesture.fromName("control+shift+leftArrow").send()
            return True
        except Exception:
            log.debugWarning("SuperTools: could not select with the keyboard", exc_info=True)
        return False

    def _getClipboardText(self):
        try:
            return api.getClipData()
        except Exception:
            return None

    def _setClipboardText(self, text):
        try:
            api.copyToClip(text)
            return True
        except Exception:
            log.debugWarning("SuperTools: clipboard could not be written", exc_info=True)
            return False

    def _replaceSelectedText(self, text):
        """Paste over the selection, putting the old clipboard back if asked to."""
        previous = self._getClipboardText() if _cfg_get_bool("clipboard_restore", True) else None
        if not self._setClipboardText(text):
            ui.message(_("Error: {e}").format(e="clipboard"))
            return
        try:
            import keyboardHandler
            keyboardHandler.KeyboardInputGesture.fromName("control+v").send()
        except Exception as ex:
            log.error("SuperTools: paste failed", exc_info=True)
            ui.message("Error: {}".format(ex))
            return
        if previous is not None:
            # The paste needs a moment before the clipboard may be changed back.
            wx.CallLater(400, self._setClipboardText, previous)

    def _openSettings(self):
        if self._settingsOpen:
            return
        self._settingsOpen = True
        wx.CallAfter(self._popupSettings)

    def _popupSettings(self):
        try:
            popup = getattr(gui.mainFrame, "popupSettingsDialog", None) or gui.mainFrame._popupSettingsDialog
            try:
                popup(SettingsDialog)
            except gui.settingsDialogs.SettingsDialog.MultiInstanceError:
                # A previous dialog was destroyed but its Python object is still
                # alive (it is only freed once the garbage collector runs), and
                # NVDA then refuses to open a new one. Collect and try again.
                if not _release_settings_instances():
                    raise
                popup(SettingsDialog)
        except Exception as ex:
            log.error("SuperTools: settings dialog failed to open", exc_info=True)
            ui.message("Settings error: {}".format(ex))
        finally:
            self._settingsOpen = False

    def _isEnabled(self, key):
        return _cfg_get_bool(key + "_enabled", True)

    def _commandSound(self, key):
        if not _cfg_get_bool("command_sounds", True):
            return
        _play_event(key, _get_command_sound(key))

    def _installCapture(self):
        """
        Take over the keyboard. Command mode and the keyboard lock both need
        this, and they can be on at the same time, so it is installed once and
        taken away only when neither of them wants it any more.
        """
        import inputCore
        if getattr(inputCore.manager, "_captureFunc", None) != self._captureCommandGesture:
            self._commandCapture = getattr(inputCore.manager, "_captureFunc", None)
            inputCore.manager._captureFunc = self._captureCommandGesture

    def _removeCapture(self):
        if self._commandMode or self._locked:
            return
        try:
            import inputCore
            if getattr(inputCore.manager, "_captureFunc", None) == self._captureCommandGesture:
                inputCore.manager._captureFunc = self._commandCapture
        except Exception:
            log.debugWarning("SuperTools: could not release the keyboard", exc_info=True)
        self._commandCapture = None

    def _startCommandMode(self):
        if self._commandMode:
            return
        try:
            self._installCapture()
            self._commandMode = True
        except Exception as ex:
            log.error("SuperTools: command mode could not start", exc_info=True)
            ui.message("Command mode could not start: {}".format(ex))
            return
        self._startCommandTimeout()
        self._commandSound("start")
        ui.message(_("Command mode. H help, X changes, C layout, Shift+C convert the word "
                     "before the cursor, Z undo, S settings, W word monitor, Shift+W toggle "
                     "word monitor, P process manager, L lock the keyboard, T clock, "
                     "U look for a new version, Escape cancel."))

    def _startCommandTimeout(self):
        """Never leave the user trapped: drop out of command mode on its own."""
        self._cancelCommandTimeout()
        if not _cfg_get_bool("command_timeout_enabled", True):
            return
        seconds = max(1, _cfg_get_int("command_timeout_seconds", 8))
        try:
            self._commandTimer = wx.CallLater(seconds * 1000, self._onCommandTimeout)
        except Exception:
            log.debugWarning("SuperTools: command timeout could not start", exc_info=True)

    def _cancelCommandTimeout(self):
        timer = getattr(self, "_commandTimer", None)
        self._commandTimer = None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass

    def _onCommandTimeout(self):
        self._commandTimer = None
        if not self._commandMode:
            return
        self._stopCommandMode()
        self._commandSound("escape")
        ui.message(_("Command mode ended."))

    def _stopCommandMode(self):
        if not self._commandMode:
            return
        self._commandMode = False
        self._removeCapture()
        self._cancelCommandTimeout()

    # command key -> (feature it belongs to, method)
    def _commandActions(self):
        return {"h":       ("",   self._showHelp),
                "x":       ("",   self._showChanges),
                "c":       ("kb", self._doConvert),
                "shift+c": ("kb", self._convertLastWord),
                "z":       ("kb", self._undoConvert),
                "s":       ("",   self._openSettings),
                "w":       ("wm", self._showWordDialog),
                "shift+w": ("wm", self._toggleWordMonitor),
                "p":       ("pm", self._showProcessManager),
                "l":       ("lock", self._toggleLock),
                "t":       ("clock", self._showClock),
                "u":       ("",   self._checkNow)}

    def _captureCommandGesture(self, gesture):
        """
        Runs on NVDA's input thread. Returning False swallows the key, so while
        command mode is on nothing at all reaches the focused application.
        """
        try:
            key = _command_key_from_gesture(gesture)
        except Exception:
            log.error("SuperTools: could not read command key", exc_info=True)
            key = None
        if not self._commandMode:
            # The keyboard is locked. The only key that still works is the one
            # that opens command mode, so the way out is the same two presses
            # the user already knows: the command key, then L.
            if self._isCommandModeGesture(gesture):
                return True
            if key is not None:
                self._commandSound("locked")
            return False
        if key is None:
            # Modifier keys (shift, control, NVDA...) and non-keyboard gestures
            # are not commands: keep waiting instead of leaving command mode.
            return True
        if key != "escape" and key not in self._commandActions():
            # Unknown key: stay in command mode and just report it with a beep.
            self._commandSound("unknown")
            wx.CallAfter(self._startCommandTimeout)
            return False
        self._stopCommandMode()
        wx.CallAfter(self._runCommand, key)
        return False

    def _isCommandModeGesture(self, gesture):
        """
        Is this the key that opens command mode? Asked of NVDA rather than
        assumed, so a user who has bound command mode to something else can
        still unlock their keyboard with it.
        """
        try:
            script = scriptHandler.findScript(gesture)
            if script is not None and getattr(script, "__name__", "") == "script_commandMode":
                return True
        except Exception:
            log.debugWarning("SuperTools: could not resolve a gesture", exc_info=True)
        try:
            for identifier in getattr(gesture, "identifiers", ()) or ():
                if str(identifier).lower().replace(" ", "").endswith("nvda+shift+u"):
                    return True
        except Exception:
            pass
        return False

    def _toggleLock(self):
        """
        Lock or unlock the keyboard.

        While it is locked every key is swallowed before it reaches anything -
        NVDA included - except the one that opens command mode, so L can undo
        it. Nothing is remembered: a lock ends when NVDA does, which is the
        last way out if anything goes wrong.
        """
        self._locked = not self._locked
        try:
            if self._locked:
                self._installCapture()
            else:
                self._removeCapture()
        except Exception:
            log.error("SuperTools: the keyboard lock failed", exc_info=True)
            self._locked = False
            ui.message(_("The keyboard could not be locked."))
            return
        _play_event("lock_on" if self._locked else "lock_off",
                    [[880, 70], [440, 120]] if self._locked else [[440, 70], [880, 120]])
        if self._locked:
            ui.message(_("Keyboard locked. Press NVDA+Shift+U and then L to unlock it."))
        else:
            ui.message(_("Keyboard unlocked."))

    def _showClock(self):
        """T in command mode: how far the clock is out, and how to fix it."""
        self._showDialog(ClockDialog)

    def _runCommand(self, key):
        if key == "escape":
            self._commandSound("escape")
            ui.message(_("Command mode cancelled."))
            return
        feature, action = self._commandActions().get(key, (None, None))
        if not action:
            self._commandSound("unknown")
            return
        self._commandSound(key)
        if feature and not self._isEnabled(feature):
            ui.message(_("This feature is disabled in SuperTools settings."))
            return
        action()

    @scriptHandler.script(gesture="kb:NVDA+shift+u",
                          description="Open one-key SuperTools command mode.",
                          category=scriptCategory)
    def script_commandMode(self, gesture):
        self._startCommandMode()

    def _toggleWordMonitor(self):
        enabled = not _get_monitor_enabled()
        _set_monitor_enabled(enabled)
        _play_event("monitor_on" if enabled else "monitor_off",
                    [[2000, 150]] if enabled else [[200, 150]])
        ui.message(_("Word monitor enabled.") if enabled else _("Word monitor disabled."))

    def _undoConvert(self):
        """
        Put back what was there before a conversion. The text is looked up in
        the history, so this only ever restores something this add-on changed.
        """
        if not self._history:
            ui.message(_("There is nothing to undo."))
            return
        selected = self._getSelectedText()
        if not selected:
            if not self._selectWordBeforeCaret():
                ui.message(_("No text selected."))
                return
            wx.CallLater(80, self._undoSelection)
            return
        self._undoSelection()

    def _undoSelection(self):
        selected = (self._getSelectedText() or "").strip()
        for index in range(len(self._history) - 1, -1, -1):
            converted, original = self._history[index]
            if selected and selected == converted.strip():
                del self._history[index]
                self._replaceSelectedText(original)
                ui.message(_("Undone: {text}").format(text=original))
                return
        ui.message(_("This text was not converted by SuperTools."))

    def _convertLastWord(self):
        """Convert the word the cursor sits behind, without selecting it first."""
        if not self._selectWordBeforeCaret():
            ui.message(_("No text selected."))
            return
        # The application needs a moment to report the new selection.
        wx.CallLater(80, self._doConvert)

    def _doConvert(self):
        try:
            text = self._getSelectedText()
            if not text:
                ui.message(_("No text selected.")); return
            source, target, name = _next_layout(text)
            if not source or not target:
                ui.message(_("Only one keyboard layout is installed, so there is nothing "
                             "to convert between.")); return
            converted = convert_text(text, source, target)
            if converted == text:
                ui.message(_("No characters to convert.")); return
            self._history.append((converted, text))
            del self._history[:-CONVERT_HISTORY]
            self._replaceSelectedText(converted)
            if _cfg_get_bool("convert_announce", True):
                if _cfg_get_bool("convert_say_layout", False):
                    ui.message(_("{text}, in {layout}").format(text=converted, layout=name))
                else:
                    ui.message(_("Converted: {text}").format(text=converted))
        except Exception as ex:
            ui.message("Convert error: {}".format(ex))

    def _showDialog(self, dialogClass, onOk=None, *args):
        """
        Show one modal dialog at a time per dialog type and always destroy it,
        so no dialog is left behind holding the add-on's data alive.
        """
        name = dialogClass.__name__
        if name in self._openDialogs:
            return
        self._openDialogs.add(name)
        dlg = None
        try:
            gui.mainFrame.prePopup()
            dlg = dialogClass(gui.mainFrame, *args)
            result = dlg.ShowModal()
            if onOk and result == wx.ID_OK:
                onOk(dlg)
        except Exception as ex:
            log.error("SuperTools: {} failed".format(name), exc_info=True)
            ui.message("{} error: {}".format(name, ex))
        finally:
            if dlg:
                dlg.Destroy()
            try:
                gui.mainFrame.postPopup()
            except Exception:
                pass
            self._openDialogs.discard(name)

    def _showWordDialog(self):
        self._showDialog(WordListDialog,
                         lambda dlg: _set_word_categories(dlg.getCategories()),
                         _get_word_categories())

    def _showProcessManager(self):
        self._showDialog(ProcessManagerDialog)

