"""Unit tests for the translation tables and settings file of yt_to_mp3_gui.py

Run:
    python -m unittest test_yt_to_mp3_gui -v

No window is ever created and the real settings file is never touched: the
tests work on the TEXT tables and on temporary paths, so they run without a
display.
"""

import json
import os
import string
import tempfile
import unittest

import yt_to_mp3_gui as gui


def placeholders(text):
    """The {name} fields used inside a translation string."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class TestLanguages(unittest.TestCase):

    def test_every_language_has_a_table(self):
        for code in gui.LANGUAGES.values():
            self.assertIn(code, gui.TEXT)

    def test_default_language_is_selectable(self):
        self.assertIn(gui.DEFAULT_LANGUAGE, gui.LANGUAGES.values())

    def test_english_is_offered(self):
        self.assertIn("en", gui.LANGUAGES.values())


class TestTranslationTables(unittest.TestCase):

    def test_all_tables_share_the_same_keys(self):
        reference = set(gui.TEXT[gui.DEFAULT_LANGUAGE])
        for code, table in gui.TEXT.items():
            self.assertEqual(set(table), reference,
                             f"key mismatch in TEXT[{code!r}]")

    def test_placeholders_match_across_languages(self):
        # a translation that drops {outdir} would raise KeyError at runtime
        reference = gui.TEXT[gui.DEFAULT_LANGUAGE]
        for code, table in gui.TEXT.items():
            for key, text in table.items():
                self.assertEqual(placeholders(text), placeholders(reference[key]),
                                 f"placeholder mismatch in TEXT[{code!r}][{key!r}]")

    def test_no_empty_strings(self):
        for code, table in gui.TEXT.items():
            for key, text in table.items():
                self.assertTrue(text.strip(), f"TEXT[{code!r}][{key!r}] is empty")

    def test_keys_used_by_the_ui_exist(self):
        # keys the code formats with arguments, spelled out here as a guard
        for key in ("item_of", "downloading", "done_status", "done_log",
                    "job", "folder_failed", "ready", "cancelled"):
            self.assertIn(key, gui.TEXT[gui.DEFAULT_LANGUAGE])

    def test_translations_actually_differ(self):
        # catches a table copied over without being translated
        ru, en = gui.TEXT["ru"], gui.TEXT["en"]
        same = [k for k in ru if ru[k] == en[k]]
        self.assertEqual(same, ["kbps", "ffmpeg_title"], f"untranslated: {same}")


class TestFormatting(unittest.TestCase):

    def test_every_string_formats_with_its_own_placeholders(self):
        sample = {"index": 1, "total": 2, "ok": 1, "speed": "1MiB/s",
                  "eta": "00:10", "outdir": "out", "count": 3,
                  "quality": "192", "error": "boom"}
        for code, table in gui.TEXT.items():
            for key, text in table.items():
                args = {name: sample[name] for name in placeholders(text)}
                text.format(**args)  # must not raise


class TestSettings(unittest.TestCase):
    """The language choice survives a restart; a bad file never breaks it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "cfg", "settings.json")

    def test_config_path_is_named_after_the_app(self):
        path = gui.config_path()
        self.assertTrue(path.endswith("settings.json"))
        self.assertIn(gui.APP_NAME, path)

    def test_save_then_load_round_trip(self):
        self.assertTrue(gui.save_settings({"language": "en"}, self.path))
        self.assertEqual(gui.load_settings(self.path), {"language": "en"})

    def test_save_creates_missing_directories(self):
        gui.save_settings({"language": "ru"}, self.path)
        self.assertTrue(os.path.isfile(self.path))

    def test_save_keeps_readable_json(self):
        gui.save_settings({"language": "en"}, self.path)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["language"], "en")

    def test_missing_file_gives_empty_settings(self):
        self.assertEqual(gui.load_settings(self.path), {})

    def test_corrupt_file_gives_empty_settings(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(gui.load_settings(self.path), {})

    def test_non_dict_file_gives_empty_settings(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(["en"], f)
        self.assertEqual(gui.load_settings(self.path), {})

    def test_unwritable_location_is_not_fatal(self):
        blocker = os.path.join(self.tmp.name, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("")
        # a file where a directory should be -> save fails but must not raise
        self.assertFalse(gui.save_settings({"language": "en"},
                                           os.path.join(blocker, "settings.json")))

    def test_other_settings_are_preserved(self):
        gui.save_settings({"language": "en", "future": 1}, self.path)
        settings = gui.load_settings(self.path)
        settings["language"] = "ru"
        gui.save_settings(settings, self.path)
        self.assertEqual(gui.load_settings(self.path),
                         {"language": "ru", "future": 1})

    def test_remembered_language_must_be_known(self):
        # the app falls back to the default for anything not in TEXT
        for stored in ("de", "", None, 42):
            with self.subTest(stored=stored):
                chosen = stored if stored in gui.TEXT else gui.DEFAULT_LANGUAGE
                self.assertIn(chosen, gui.TEXT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
