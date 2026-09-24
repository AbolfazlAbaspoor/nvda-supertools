"""
The test suite.

    python tests/test_supertools.py

It imports the add-on with NVDA and wxPython replaced by stand-ins, so
everything that is not a window can be exercised without NVDA running: the
layout conversion against the real Windows keyboard layouts, the word
matching, the process list, the translation and theme files, and how fast the
parts that run on every spoken phrase are.
"""
import sys, os, re, types, json, tempfile, time

class AnyModule(types.ModuleType):
    """Module whose unknown attributes are permissive dummies."""
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name[:1].isupper():
            cls = type(name, (Dummy,), {})
            setattr(self, name, cls)
            return cls
        setattr(self, name, 1)
        return 1

class Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, name): return Dummy()
    def __call__(self, *a, **k): return Dummy()
    def __or__(self, other): return 1
    def __ror__(self, other): return 1

def stub(name, **attrs):
    m = AnyModule(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

class _Section(dict):
    pass

class _Conf(dict):
    def save(self): self.saved = True

conf = _Conf()
conf["superTools"] = _Section({"beeps": ['[440, 200]', '[550, 200]'], "words": "hello",
                               "language": "en"})

stub("wx")
stub("globalPluginHandler", GlobalPlugin=type("GP", (), {}))
stub("api"); stub("ui", message=lambda *a, **k: None)
stub("scriptHandler", script=lambda **kw: (lambda f: f))
stub("textInfos", POSITION_SELECTION=0)
stub("addonHandler", initTranslation=lambda: None)
stub("config", conf=conf)
gui = stub("gui")
gui.settingsDialogs = types.SimpleNamespace(
    SettingsDialog=type("SettingsDialog", (Dummy,), {"_instances": {}}))
stub("speech"); stub("speechViewer", SPEECH_ITEM_SEPARATOR=" ")
stub("tones", beep=lambda f, d: played.append((f, d)))
stub("versionInfo", version_year=2026)
cfgdir = tempfile.mkdtemp()
stub("globalVars", appArgs=types.SimpleNamespace(configPath=cfgdir))
stub("logHandler", log=types.SimpleNamespace(
    error=lambda *a, **k: None, warning=lambda *a, **k: None,
    debugWarning=lambda *a, **k: None, info=lambda *a, **k: None))

played = []
ADDON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ADDON, "globalPlugins"))
import superTools as main

ok = True
def check(label, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("PASS " if good else "FAIL ") + label, "->", repr(got), "" if good else "(want %r)" % (want,))

def all_words():
    return [w["text"] for c in main._get_word_categories() for w in c["words"]]

# 1. legacy migration out of nvda.ini
check("legacy word migrated", all_words(), ["hello"])
check("broken value removed from ini", "beeps" in conf["superTools"], False)

# 2. round trip through the data file
cats = main._get_word_categories()
cats[0]["words"].append({"text": "don't \"quote\" me", "enabled": True, "inherit": True})
main._set_word_categories(cats)
main._data_cache = None                      # force a reload from disk
main._forget_word_categories()
check("words survive a restart", all_words(), ["hello", "don't \"quote\" me"])
check("data file written", os.path.exists(main._data_path()), True)

# 3. command sounds differ per command
sounds = main._get_command_sounds()
check("every command has its own sound",
      len({json.dumps(v) for v in sounds.values()}), len(sounds))
main._set_command_sounds({"h": [[1000, 50]]})
main._data_cache = None
check("custom command sound kept", main._get_command_sound("h"), [[1000, 50]])
check("other commands keep defaults", main._get_command_sound("p"), main.COMMAND_SOUND_DEFAULTS["p"])

# 4. command key parsing
class G:
    def __init__(self, ids, vk=None, isModifier=False):
        self.identifiers = ids; self.isModifier = isModifier
        if vk is not None: self.vkCode = vk
check("plain letter", main._command_key_from_gesture(G(["kb:w"], 0x57)), "w")
check("shift+letter", main._command_key_from_gesture(G(["kb:shift+w"], 0x57)), "shift+w")
check("lone right shift", main._command_key_from_gesture(G(["kb:rightShift"], 0xA1, True)), None)
check("lone shift without flag", main._command_key_from_gesture(G(["kb:rightShift"], 0xA1)), None)
check("escape", main._command_key_from_gesture(G(["kb:escape"], 0x1B)), "escape")
check("persian layout letter", main._command_key_from_gesture(G(["kb:ص"], 0x57)), "w")
check("non keyboard gesture", main._command_key_from_gesture(G(["br(x):dot1"])), None)

# 5. command mode is the only way in
plugin = object.__new__(main.GlobalPlugin)
actions = plugin._commandActions()
check("commands", sorted(actions),
      sorted(["h", "x", "c", "shift+c", "z", "s", "w", "shift+w", "p", "l", "t", "u"]))
check("process manager moved off r", "r" in actions, False)
source = open(os.path.join(ADDON, "globalPlugins", "superTools.py"), encoding="utf-8").read()
check("only the command mode gesture exists", source.count('gesture="kb:'), 1)
check("command mode gesture", 'gesture="kb:NVDA+shift+u"' in source, True)
check("nothing is sent to the application", "gesture.send()" in source, False)
check("no shortcut capture dialog", "ShortcutCaptureDialog" in source, False)
check("no shortcut binding left", "bindGesture(" in source, False)
check("no pass-through setting", "command_passthrough" in source, False)
check("processes launched detached", "CREATE_BREAKAWAY_FROM_JOB" in source, True)

# 6. beep text parsing
check("parse", main._parse_beep_text("440,100; 880,50"), [[440, 100], [880, 50]])
check("parse junk falls back", main._parse_beep_text("nonsense", [[1, 2]]), [[1, 2]])
check("format", main._format_beep_text([[440, 100], [880, 50]]), "440,100; 880,50")

# 7. conversion walks every layout the user has
import ctypes
_load = ctypes.windll.user32.LoadKeyboardLayoutW
_load.restype = ctypes.c_void_p
en = _load("00000409", 0)
fa = _load("00000429", 0)
SALAM = "\u0633\u0644\u0627\u0645"

check("latin text is recognised as english",
      main._detect_layout("hello", main._get_installed_layouts()), en)
check("persian text is recognised as persian",
      main._detect_layout(SALAM, main._get_installed_layouts()), fa)

main._cfg_set("kb_layouts", "")

def convert(text):
    from_layout, to_layout, _name = main._next_layout(text)
    return main.convert_text(text, from_layout, to_layout)

check("persian becomes english", convert(SALAM), "sghl")
check("english becomes persian", convert("sghl"), SALAM)
check("and back again", convert(convert(SALAM)), SALAM)

# With three layouts the next one is the next one, and it comes back around.
three = [("English", "0409", en), ("Persian", "0429", fa), ("Made up", "0999", 999)]
_real_layout_order = main._layout_order
main._layout_order = lambda: three
from_layout, to_layout, name = main._next_layout("hello")
check("english goes to the layout after it", (from_layout, to_layout, name), (en, fa, "Persian"))
from_layout, to_layout, name = main._next_layout(SALAM)
check("persian goes to the one after that", (to_layout, name), (999, "Made up"))
main._layout_order = lambda: three[:1]
check("one layout alone has nowhere to go", main._next_layout("hello"), (None, None, ""))
main._layout_order = _real_layout_order

# A layout can be left out of the ring.
main._cfg_set("kb_layouts", "0409")
check("a list of one is ignored, since two are needed",
      len(main._layout_order()), len(main._get_installed_layouts()))
main._cfg_set("kb_layouts", "")

# 8. per-word settings: matching, inheritance and muting
cats = main._default_word_categories()
cats[0]["words"] = [
    {"text": "hi", "enabled": True, "inherit": True},
    {"text": "boss", "enabled": True, "inherit": False, "match": "word",
     "action": "mute", "beeps": [[100, 10]]},
    {"text": "Ali", "enabled": True, "inherit": False, "case": True, "action": "speak",
     "prefix": "friend"},
]
main._set_word_categories(cats)

def matched(text):
    return sorted(w for w, _s in main._find_word_matches(text))

check("partial match by default", matched("this is hidden"), ["hi"])
check("whole word only", matched("bosses are here"), [])
check("whole word hit", matched("the boss said hi"), ["boss", "hi"])
check("case sensitive miss", matched("ali called"), [])
check("case sensitive hit", matched("Ali called"), ["Ali"])
settings = dict(main._find_word_matches("the boss said")[0][1])
check("muted word removed", main._mute_word("the boss said", "boss", settings).split(),
      ["the", "said"])
check("word inherits the category", main._word_settings(cats[0], cats[0]["words"][0])["action"],
      cats[0]["action"])
check("word keeps its own settings", main._word_settings(cats[0], cats[0]["words"][1])["action"],
      "mute")

plugin = object.__new__(main.GlobalPlugin)
seq, alerts = plugin._applyWordMonitor(["the boss said hi"])
check("muted word taken out of the sentence", seq, ["the said hi"])
check("muted word still alerts", bool(alerts), True)
seq, _alerts = plugin._applyWordMonitor(["boss"])
check("utterance of only a muted word is dropped", seq, [])
seq, alerts = plugin._applyWordMonitor(["Ali called"])
check("prefix is spoken", seq[0].startswith("friend "), True)
check("speak only means no alert", alerts, [])

# 9. importing word lists
check("words from lines", main._split_word_list("one\ntwo\n"), ["one", "two"])
check("words from commas", main._split_word_list("one, two"), ["one", "two"])
check("words from json", main._split_word_list('["one", {"text": "two"}]'), ["one", "two"])

# 10. process rows: filtering by PID and sorting
rows = [(20, "b.exe", 300, 5.0, "B Ltd"), (5, "a.exe", 900, 50.0, "A Ltd"),
        (30, "c.exe", 100, 0.0, "C Ltd")]
check("filter by name", [r[1] for r in main._filter_process_rows(rows, "a.ex")], ["a.exe"])
check("filter by pid", [r[0] for r in main._filter_process_rows(rows, "3")], [30])
check("sort by cpu", [r[0] for r in main._sort_process_rows(rows, "cpu")], [5, 20, 30])
check("sort by memory", [r[0] for r in main._sort_process_rows(rows, "memory")], [5, 20, 30])
check("sort by pid", [r[0] for r in main._sort_process_rows(rows, "pid")], [5, 20, 30])
check("sort by name", [r[1] for r in main._sort_process_rows(rows, "name")],
      ["a.exe", "b.exe", "c.exe"])

# 11. settings backup
backup = os.path.join(cfgdir, "backup.json")
main._export_settings(backup)
main._data_cache = None
saved = json.load(open(backup, encoding="utf-8"))
check("backup holds the settings", sorted(saved), ["config", "data", "supertools"])
check("backup holds the words", "word_categories" in saved["data"], True)
check("import rejects a foreign file",
      main._import_settings(os.path.join(cfgdir, "superTools.json")), False)
check("import accepts its own file", main._import_settings(backup), True)

# 12. translations come from NVDA's own catalogues
import gettext
for code, english, expected in [("fa", "No text selected.", "\u0645\u062a\u0646\u06cc \u0627\u0646\u062a\u062e\u0627\u0628 \u0646\u0634\u062f\u0647 \u0627\u0633\u062a."),
                                ("de", "Word Monitor", "Wort\u00fcberwachung"),
                                ("ru", "Categories", "\u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0438")]:
    catalog = gettext.translation("nvda", localedir=os.path.join(ADDON, "locale"),
                                  languages=[code], fallback=True)
    check("catalogue " + code, catalog.gettext(english), expected)
catalog = gettext.translation("nvda", localedir=os.path.join(ADDON, "locale"),
                              languages=["xx"], fallback=True)
check("unknown language falls back to english", catalog.gettext("Categories"), "Categories")
check("no json language system left", "superToolsLanguages" in source, False)
check("no key table left", "STRINGS" in source, False)

# 13. the word matcher is prepared once, not per phrase
cats = main._default_word_categories()
cats[0]["words"] = [{"text": "word%d" % i, "enabled": True, "inherit": True} for i in range(200)]
main._set_word_categories(cats)
main._find_word_matches("warm up")
started = time.perf_counter()
for _i in range(2000):
    main._find_word_matches("a sentence NVDA might speak with word7 in it")
elapsed = (time.perf_counter() - started) / 2000 * 1000
print("      matching 200 words takes %.3f ms per phrase" % elapsed)
check("matching is fast enough for every phrase", elapsed < 1.0, True)
check("cache is dropped when words change",
      (main._set_word_categories(cats), main._matchers_cache)[1], None)

# 14. rules per application
plugin._isEnabled = lambda key: True
main._cfg_set("wm_app_mode", "only")
main._cfg_set("wm_apps", "notepad, chrome.exe")
main._forget_app_rules()
main._current_app = lambda: "notepad"
check("allowed in a listed application", main._feature_allowed_here("wm"), True)
main._current_app = lambda: "winword"
check("blocked elsewhere", main._feature_allowed_here("wm"), False)
main._cfg_set("wm_app_mode", "except")
main._forget_app_rules()
check("except list lets others through", main._feature_allowed_here("wm"), True)
main._current_app = lambda: "chrome"
check("except list blocks the listed one", main._feature_allowed_here("wm"), False)
main._cfg_set("wm_app_mode", "all")
main._forget_app_rules()
check("no rule means everywhere", main._feature_allowed_here("wm"), True)

# 15. a word can play a sound file instead of beeps
played_files = []
main._play_sound_file = lambda path: played_files.append(path) or True
settings = main._normalize_word_settings({"sound": r"C:\does\not\exist.wav"})
check("a missing file falls back to beeps", settings["sound"].endswith(".wav"), True)
wav = os.path.join(cfgdir, "alert.wav")
open(wav, "wb").write(b"RIFF")
main._play_alert(main._normalize_word_settings({"sound": wav}))
check("the sound file is played", played_files, [wav])

# 16. how often a word was heard
main._word_counts = None
main._count_word("boss"); main._count_word("boss"); main._count_word("hi")
check("counted per word", main._get_word_counts()["boss"], 2)
main._save_word_counts()
main._data_cache = None
main._word_counts = None
check("counts survive a restart", main._get_word_counts()["hi"], 1)

# 17. the check on what was typed
seen = []
plugin._convertLastWord = lambda: seen.append("converted")
main._play_sequence = lambda *a, **k: seen.append("beep")
main._cfg_set("autocheck_enabled", True)
main._cfg_set("autocheck_convert", False)
main._current_app = lambda: "notepad"
main._forget_app_rules()
plugin._checkTypedWord("sghl")
check("a word with no vowel is suspicious", seen, ["beep"])
seen[:] = []
plugin._checkTypedWord("hello")
check("an ordinary word is left alone", seen, [])
seen[:] = []
plugin._checkTypedWord("hi")
check("very short words are ignored", seen, [])
seen[:] = []
plugin._checkTypedWord("\u0633\u0644\u0627\u0645")
check("persian text is left alone", seen, [])

# 18. undo remembers only what this add-on converted
plugin._history = [("sghl", "\u0633\u0644\u0627\u0645")]
replaced = []
plugin._replaceSelectedText = lambda text: replaced.append(text)
plugin._getSelectedText = lambda: "sghl"
plugin._undoSelection()
check("undo restores the original", replaced, ["\u0633\u0644\u0627\u0645"])
check("the entry is used up", plugin._history, [])
plugin._getSelectedText = lambda: "something else"
plugin._undoSelection()
check("other text is not touched", replaced, ["\u0633\u0644\u0627\u0645"])

# 19. the weekly backup
main._cfg_set("backup_weekly", True)
main._cfg_set("backup_last", 0)
main._weekly_backup()
for _i in range(50):
    files = os.listdir(main._backup_dir()) if os.path.isdir(main._backup_dir()) else []
    if files:
        break
    time.sleep(0.02)
check("a backup was written", bool(files), True)
before = main._cfg_get_int("backup_last", 0)
main._weekly_backup()
check("it does not run again the same week", main._cfg_get_int("backup_last", 0), before)

# 20. the process list comes from Windows itself
rows = main._get_process_rows()
check("windows gives the whole list", len(rows) > 20, True)
check("every row is complete", all(len(r) == 5 for r in rows), True)
check("names are filled in", all(r[1] for r in rows), True)
check("memory is known for nearly every process",
      sum(1 for r in rows if r[2] > 0) > len(rows) * 0.9, True)
me = os.getpid()
check("this very process is listed", any(r[0] == me for r in rows), True)
check("its program is found", main._process_path(me).lower().endswith("python.exe"), True)
info = main._process_info(me)
check("details without psutil", (bool(info["name"]), info["memory"] > 0), (True, True))

started = time.perf_counter()
for _i in range(20):
    main._get_process_rows()
per = (time.perf_counter() - started) / 20 * 1000
print("      listing %d processes takes %.1f ms" % (len(rows), per))
check("the list is fast enough to refresh often", per < 50, True)

main._get_process_rows(True)
time.sleep(0.3)
busy = main._get_process_rows(True)
check("processor use is measured", any(r[3] > 0 for r in busy), True)
check("publisher is read", any(r[4] for r in busy), True)

# 21. sound themes
main._forget_themes()
main._cfg_set("sound_theme", "")
check("no theme means built-in beeps", main._theme_sound("start"), None)
themes = dict(main._theme_items())
check("the shipped theme is found", any("Soft" in label for label in themes.values()), True)
check("the built-in entry comes first", list(themes)[0], "")
check("the author is credited in the list",
      any("Abolfazl" in label for label in themes.values()), True)

main._cfg_set("sound_theme", "soft")
main._forget_themes()
check("a theme replaces a beep", main._theme_sound("start")["beeps"], [[392, 45], [523, 55]])
check("a sound the theme skips falls back", main._theme_sound("nothing-like-this"), None)

themedir = os.path.join(cfgdir, "superToolsThemes")
os.makedirs(themedir, exist_ok=True)
open(os.path.join(themedir, "alert.wav"), "wb").write(b"RIFF")
json.dump({"name": "Files", "author": "Someone",
           "sounds": {"start": {"file": "alert.wav"}, "h": {"file": "missing.wav"}}},
          open(os.path.join(themedir, "files.json"), "w", encoding="utf-8"))
main._cfg_set("sound_theme", "files")
main._forget_themes()
check("a theme can use a sound file",
      os.path.basename(main._theme_sound("start")["file"]), "alert.wav")
check("a missing file falls back to the beep", main._theme_sound("h"), None)

played_files = []
main._play_sound_file = lambda path: played_files.append(os.path.basename(path)) or True
beeped = []
main._play_sequence = lambda beeps, gap=0, interrupt=False: beeped.append(list(beeps))
main._play_event("start", [[1, 2]])
check("the theme sound is played, not the beep", (played_files, beeped), (["alert.wav"], []))
main._play_event("h", [[1, 2]])
check("the built-in beep plays when the theme is silent", beeped, [[[1, 2]]])

template = os.path.join(cfgdir, "template.json")
main._write_theme_template(template, main._get_command_sounds())
made = json.load(open(template, encoding="utf-8"))
check("the template offers every command sound",
      sorted(made["sounds"]) == sorted(main.COMMAND_SOUND_DEFAULTS), True)

# 22. credits for the people behind it
credits = json.load(open(os.path.join(ADDON, "locale", "credits.json"), encoding="utf-8"))
check("every language is credited", len(credits), 10)
check("the language name is written as its own speakers write it",
      credits["fa"]["language"], "\u0641\u0627\u0631\u0633\u06cc")
check("the translator is recorded", bool(credits["fa"]["translator"]), True)
main._cfg_set("sound_theme", "files")
main._forget_themes()
who = main._credits()
check("the theme author is known", (who["theme"], who["theme_author"]), ("Files", "Someone"))
main._cfg_set("sound_theme", "")
main._forget_themes()

# 23. the version is written down in one place
manifest = open(os.path.join(ADDON, "manifest.ini"), encoding="utf-8").read()
check("the add-on reads its version from the manifest",
      'version = "{}"'.format(main._read_version()) in manifest, True)

# 24. what the wizards write
texts = main._pot_texts()
check("the list of texts to translate is readable", len(texts) > 100, True)
check("it holds the real strings", "No text selected." in texts, True)

po = os.path.join(cfgdir, "xx.po")
entries = {"No text selected.": "Nichts markiert.", "Close": "Zu"}
main._write_po_file(po, "xx", "Test", "Someone <a@b.c>", entries, texts[:20] + list(entries))
back = main._read_po_file(po)
check("what the wizard writes, it can read again",
      back.get("No text selected."), "Nichts markiert.")
check("the translator is written into the file",
      "Someone <a@b.c>" in open(po, encoding="utf-8").read(), True)

mo = os.path.join(cfgdir, "wizard.mo")
main._write_mo_file(mo, entries)
import gettext
with open(mo, "rb") as f:
    catalog = gettext.GNUTranslations(f)
check("the compiled catalogue works", catalog.gettext("No text selected."), "Nichts markiert.")
check("an untranslated text stays in english", catalog.gettext("Categories"), "Categories")

main._write_mo_file(os.path.join(ADDON, "locale", "xx", "LC_MESSAGES", "nvda.mo"), entries)
main._catalog_cache.clear()
main._cfg_set("language_override", "xx")
check("the override finds the new language", main._apply_language_override(), True)
check("and the add-on speaks it", main._("No text selected."), "Nichts markiert.")
main._cfg_set("language_override", "")
import shutil
shutil.rmtree(os.path.join(ADDON, "locale", "xx"), ignore_errors=True)

# 25. beeps that keep their timing
rate = main.TONE_RATE
lead = int(rate * main._beep_lead_in() / 1000.0)
check("a sequence starts with silence, so the first beep is not swallowed", lead > 0, True)
for sequence, gap in (([[440, 100], [880, 100]], 50), ([[500, 60]], 0), ([[400, 50]] * 4, 25)):
    samples = len(main._tone_buffer(sequence, gap)) // 2 - lead
    wanted = (sum(int(rate * ms / 1000.0) for _hz, ms in sequence)
              + int(rate * gap / 1000.0) * (len(sequence) - 1))
    check("a sequence of {} lasts exactly as long as asked".format(len(sequence)),
          samples, wanted)

main._cfg_set("beep_volume", 100)
loud = max(abs(int.from_bytes(main._tone_buffer([[440, 50]], 0)[i:i+2], "little", signed=True))
           for i in range(lead * 2, lead * 2 + 2000, 2))
main._cfg_set("beep_volume", 20)
quiet = max(abs(int.from_bytes(main._tone_buffer([[440, 50]], 0)[i:i+2], "little", signed=True))
            for i in range(lead * 2, lead * 2 + 2000, 2))
check("the volume setting is heard", loud > quiet * 2, True)
main._cfg_set("beep_volume", 35)

played = []
main.tones.beep = lambda hz, ms: played.append((hz, ms))
main._cfg_set("beep_engine", "nvda")
main._beep_one_by_one([[440, 5], [880, 5]], 5)
check("NVDA's own beep is used when chosen", played, [(440, 5), (880, 5)])
main._cfg_set("beep_engine", "exact")
check("the buffer is 16 bit", len(main._tone_buffer([[440, 10]], 0)) % 2, 0)

# 26. looking for a new version
check("a newer version is offered", main._update_available({"version": "9.9.9"}), True)
check("the same version is not",
      main._update_available({"version": main.CURRENT_VERSION}), False)
check("an older one is not", main._update_available({"version": "0.1.0"}), False)
check("nothing at all is not", main._update_available(None), False)

main._cfg_set("update_check", False)
main._cfg_set("update_last", 0)
asked = []
_real_latest_release = main._latest_release
main._latest_release = lambda: asked.append(1) or {
    "version": "9.9.9", "name": "x", "notes": "", "page": "http://example.invalid"}
main._check_for_update(lambda release, error: None)
time.sleep(0.2)
check("it stays off the network until asked for", asked, [])

answers = []
# In NVDA the answer is handed back on the GUI thread; here there is none.
main.wx.CallAfter = lambda function, *args, **kwargs: function(*args, **kwargs)
main._check_for_update(lambda release, error: answers.append((release, error)), force=True)
for _i in range(50):
    if answers:
        break
    time.sleep(0.02)
check("when asked, it reports what it found",
      (answers[0][0] or {}).get("version") if answers else None, "9.9.9")
main._cfg_set("update_check", False)
main._cfg_set("update_last", 0)

# 27. nothing published yet is not a failure
import urllib.error
import urllib.request

def _gone(*args, **kwargs):
    raise urllib.error.HTTPError("http://example.invalid", 404, "Not Found", None, None)

main._latest_release = _real_latest_release      # the real one, asking the real way
_real_urlopen = urllib.request.urlopen
urllib.request.urlopen = _gone
try:
    check("a repository with no release answers politely",
          main._latest_release(), main.NO_RELEASE)
finally:
    urllib.request.urlopen = _real_urlopen
check("and that is not offered as an update", main._update_available(main.NO_RELEASE), False)

reports = []
main._latest_release = lambda: main.NO_RELEASE
main._cfg_set("update_last", 0)
main._check_for_update(lambda release, error: reports.append((release, error)), force=True)
for _i in range(50):
    if reports:
        break
    time.sleep(0.02)
check("it is reported as nothing to compare with, not as a failure",
      reports[0] if reports else None, (main.NO_RELEASE, None))

# 28. NVDA's own beep is woken first, so its first tone is heard too
main._cfg_set("beep_lead_in", 60)
woken = []
main.tones.beep = lambda hz, ms, left=None, right=None: woken.append((hz, ms, left, right))
main._beep_one_by_one([[440, 5]], 0)
check("a silent tone wakes the device first", woken[0][2:], (0, 0))
check("then the real beep is played", woken[1][:2], (440, 5))

# 29. credit for everyone who worked on a language
people = json.load(open(os.path.join(ADDON, "locale", "credits.json"), encoding="utf-8"))
check("a language holds a list of translators",
      isinstance(people["fa"]["translators"], list), True)
check("no AI is named", "claude" in json.dumps(people).lower(), False)
check("but it does say an AI made them", "ai" in people["fa"]["translators"][0].lower(), True)

# Two people on one language, read the way the add-on reads them.
os.makedirs(os.path.join(cfgdir, "locale"), exist_ok=True)
people["fa"] = {"language": "\u0641\u0627\u0631\u0633\u06cc",
                "translators": ["First Person", "Second Person"]}
with open(os.path.join(cfgdir, "locale", "credits.json"), "w", encoding="utf-8") as f:
    json.dump(people, f, ensure_ascii=False)
_real_addon_dir = main._addon_dir
main._addon_dir = lambda: cfgdir
main._cfg_set("language_override", "fa")
who = main._credits()
check("both names come back", who["translators"], ["First Person", "Second Person"])
line = main._credits_line()
check("the line names the author of the add-on", main.ADDON_AUTHOR in line, True)
check("and both translators", "First Person, Second Person" in line, True)
main._cfg_set("language_override", "")
main._addon_dir = _real_addon_dir

check("the author is read from the manifest",
      main.ADDON_AUTHOR in open(os.path.join(ADDON, "manifest.ini"), encoding="utf-8").read(),
      True)

# 30. the release script, which is what actually reaches the store
sys.path.insert(0, os.path.join(ADDON, "tools"))
import release

fields = release.manifest()
variables = release.build_vars()
check("the release script and the add-on agree on the version",
      fields["version"], main.CURRENT_VERSION)
check("owner and repository come out of the manifest address",
      release.repository(fields["url"]), ("AbolfazlAbaspoor", "nvda-supertools"))
check("the licence comes from buildVars", variables["addon_license"], "GPL v2")
check("the release page gets the notes for this version",
      release.release_notes(fields["version"]) != "", True)

# The store's own rules, checked without asking the store.
_real_versions = release.api_versions
release.api_versions = lambda: [
    {"apiVer": {"major": 2024, "minor": 1, "patch": 0}},
    {"apiVer": {"major": 2026, "minor": 2, "patch": 0}},
    {"apiVer": {"major": 2026, "minor": 3, "patch": 0}, "experimental": True}]
check("a version tested against a released NVDA goes to the stable channel",
      release.check(fields, variables), "stable")
experimental = dict(fields, lastTestedNVDAVersion="2026.3")
check("one tested against an unreleased NVDA goes to beta",
      release.check(experimental, variables), "beta")
release.api_versions = _real_versions

check("the add-on name is one the store accepts",
      bool(re.fullmatch(r"[A-Za-z0-9_-]+", fields["name"])), True)
check("the version has the shape the store wants",
      bool(re.fullmatch(r"\d+\.\d+(\.\d+)?", fields["version"])), True)

# 31. the keyboard lock and the clock
check("every command has a sound of its own",
      sorted(set(actions) - set(main.COMMAND_SOUND_DEFAULTS)), [])
check("a locked keyboard makes no sound at all",
      "locked" in main.COMMAND_SOUND_DEFAULTS, False)
check("it says so in words instead, and rarely",
      "lock_notice_seconds" in source and "wx.CallAfter(ui.message, _(" in source, True)
check("a held-down key cannot pile up beeps",
      "unknown_beep_ms" in source, True)
check("the toggle keys are read and put back",
      "_restore_toggles" in source and "GetKeyState" in source, True)
check("everything about it can be changed",
      all(name in source for name in ("lock_announce", "lock_toggles",
                                      "lock_notice_seconds", "unknown_beep_ms")), True)
check("the lock is not remembered anywhere",
      "lock_enabled" in source and "_cfg_set(\"locked\"" not in source, True)
check("a lock ends when the add-on does",
      "self._locked = False\n        self._stopCommandMode()" in source, True)
check("the keyboard is only released when neither mode wants it",
      "if self._commandMode or self._locked:\n            return" in source, True)

check("a clock that agrees is said to be right",
      "right" in main._drift_sentence(1.0, "example.com"), True)
check("a clock that runs fast is called ahead",
      "ahead" in main._drift_sentence(300.0, "example.com"), True)
check("a clock that runs slow is called behind",
      "behind" in main._drift_sentence(-300.0, "example.com"), True)
check("a big difference is told in hours, not seconds",
      "hours" in main._drift_sentence(7200.0, "example.com"), True)
check("the clock is read from plain http too, for when https cannot work",
      any(host.startswith("http://") for host in main.CLOCK_HOSTS), True)
check("the clock is never set without Windows asking",
      'info.lpVerb = "runas"' in source, True)

# 32. the update check stays out of the way of starting NVDA
check("nothing waits for the network while NVDA starts",
      main.UPDATE_START_DELAY >= 60, True)
check("the backup waits for the same moment",
      "_weekly_backup()" in source.split("def _afterStartup")[1][:400], True)
check("a version can be skipped once and for all", "update_skip" in source, True)
check("the new version is offered, never installed by itself",
      "_download_release(release, self._onDownloaded)" in source, True)

# 33. the help of every language lists every command
for _language in sorted(os.listdir(os.path.join(ADDON, "doc"))):
    _help = os.path.join(ADDON, "doc", _language, "help.txt")
    if not os.path.isfile(_help):
        continue
    _text = open(_help, encoding="utf-8").read()
    _missing = [_key.upper() for _key in actions
                if ("  " + _key.upper() + " ") not in _text
                and ("  " + _key.title() + " ") not in _text]
    check("the {} help lists every command".format(_language), _missing, [])

# 34. the script that moves the add-on through the store
import update_store
check("the store status reads the same manifest",
      update_store.release.manifest()["version"], fields["version"])
check("versions sort the way people read them",
      sorted(["1.10.0", "1.2.0", "1.1.0"], key=release.version_tuple),
      ["1.1.0", "1.2.0", "1.10.0"])
check("it looks in the store's own repository",
      update_store.STORE, "nvaccess/addon-datastore")
check("it says why the last step is a button",
      "autoSubmissionFromIssue" in update_store.__doc__, True)
check("it reads by default and publishes only when asked",
      "--submit" in update_store.__doc__, True)

print("\nALL PASS" if ok else "\nFAILURES ABOVE")
sys.exit(0 if ok else 1)
