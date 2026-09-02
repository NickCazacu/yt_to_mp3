"""Unit tests for yt_to_mp3.py

Run:
    python -m unittest test_yt_to_mp3 -v

No network access and no ffmpeg calls: yt_dlp.YoutubeDL is replaced with a
mock in every test that reaches it.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import yt_to_mp3


def make_ydl_mock(mock_cls):
    """Wire a mocked YoutubeDL class so the "with ... as ydl" block yields a
    mock we can assert on. Returns that inner mock."""
    ydl = MagicMock()
    mock_cls.return_value.__enter__.return_value = ydl
    mock_cls.return_value.__exit__.return_value = False
    return ydl


class TestBuildOptions(unittest.TestCase):

    def test_selects_audio_only_format(self):
        opts = yt_to_mp3.build_options("out", 192, False)
        self.assertEqual(opts["format"], "bestaudio/best")

    def test_outtmpl_embeds_output_directory(self):
        opts = yt_to_mp3.build_options("D:/Music", 192, False)
        self.assertEqual(opts["outtmpl"], "D:/Music/%(title)s.%(ext)s")

    def test_outtmpl_accepts_windows_style_path(self):
        opts = yt_to_mp3.build_options(r"C:\Users\Admin\Music", 192, False)
        self.assertTrue(opts["outtmpl"].startswith(r"C:\Users\Admin\Music"))
        self.assertTrue(opts["outtmpl"].endswith("%(title)s.%(ext)s"))

    def test_noplaylist_is_inverted_flag(self):
        # --playlist absent -> single video only
        self.assertTrue(yt_to_mp3.build_options("out", 192, False)["noplaylist"])
        # --playlist given -> whole playlist
        self.assertFalse(yt_to_mp3.build_options("out", 192, True)["noplaylist"])

    def test_progress_hook_is_registered(self):
        opts = yt_to_mp3.build_options("out", 192, False)
        self.assertEqual(opts["progress_hooks"], [yt_to_mp3.progress_hook])

    def test_extract_audio_postprocessor_configured_for_mp3(self):
        opts = yt_to_mp3.build_options("out", 320, False)
        extract = opts["postprocessors"][0]
        self.assertEqual(extract["key"], "FFmpegExtractAudio")
        self.assertEqual(extract["preferredcodec"], "mp3")

    def test_quality_is_stringified(self):
        # yt-dlp expects preferredquality as a string, not an int
        extract = yt_to_mp3.build_options("out", 320, False)["postprocessors"][0]
        self.assertEqual(extract["preferredquality"], "320")
        self.assertIsInstance(extract["preferredquality"], str)

    def test_metadata_postprocessor_runs_after_extraction(self):
        # order matters: tags must be written onto the finished mp3
        opts = yt_to_mp3.build_options("out", 192, False)
        keys = [p["key"] for p in opts["postprocessors"]]
        self.assertEqual(keys, ["FFmpegExtractAudio", "FFmpegMetadata"])

    def test_runs_quietly(self):
        opts = yt_to_mp3.build_options("out", 192, False)
        self.assertTrue(opts["quiet"])
        self.assertTrue(opts["no_warnings"])


class TestProgressHook(unittest.TestCase):

    def run_hook(self, payload):
        buf = io.StringIO()
        with redirect_stdout(buf):
            yt_to_mp3.progress_hook(payload)
        return buf.getvalue()

    def test_downloading_reports_percent_and_speed(self):
        out = self.run_hook({
            "status": "downloading",
            "_percent_str": " 42.0%",
            "_speed_str": "1.20MiB/s",
        })
        self.assertIn("42.0%", out)
        self.assertIn("1.20MiB/s", out)

    def test_downloading_rewrites_same_line(self):
        out = self.run_hook({
            "status": "downloading",
            "_percent_str": "5%",
            "_speed_str": "1B/s",
        })
        self.assertTrue(out.startswith("\r"))
        self.assertFalse(out.endswith("\n"))

    def test_downloading_tolerates_missing_stats(self):
        # yt-dlp omits _percent_str/_speed_str on the very first callback
        out = self.run_hook({"status": "downloading"})
        self.assertIn("downloading", out)

    def test_finished_announces_conversion(self):
        out = self.run_hook({"status": "finished"})
        self.assertIn("converting to mp3", out)
        self.assertTrue(out.endswith("\n"))

    def test_unknown_status_prints_nothing(self):
        self.assertEqual(self.run_hook({"status": "error"}), "")


@patch("yt_to_mp3.yt_dlp.YoutubeDL")
class TestDownload(unittest.TestCase):

    def test_returns_empty_list_when_all_succeed(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        ydl.extract_info.return_value = {"title": "Some Song"}
        with redirect_stdout(io.StringIO()):
            failed = yt_to_mp3.download(["u1", "u2"], "out", 192, False)
        self.assertEqual(failed, [])
        self.assertEqual(ydl.extract_info.call_count, 2)

    def test_passes_built_options_to_youtubedl(self, mock_cls):
        make_ydl_mock(mock_cls)
        with redirect_stdout(io.StringIO()):
            yt_to_mp3.download(["u1"], "MyDir", 320, True)
        opts = mock_cls.call_args[0][0]
        self.assertEqual(opts["outtmpl"], "MyDir/%(title)s.%(ext)s")
        self.assertFalse(opts["noplaylist"])
        self.assertEqual(opts["postprocessors"][0]["preferredquality"], "320")

    def test_requests_an_actual_download(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        ydl.extract_info.return_value = {"title": "T"}
        with redirect_stdout(io.StringIO()):
            yt_to_mp3.download(["https://example/watch?v=1"], "out", 192, False)
        ydl.extract_info.assert_called_once_with(
            "https://example/watch?v=1", download=True
        )

    def test_reuses_one_youtubedl_for_all_urls(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        ydl.extract_info.return_value = {"title": "T"}
        with redirect_stdout(io.StringIO()):
            yt_to_mp3.download(["a", "b", "c"], "out", 192, False)
        self.assertEqual(mock_cls.call_count, 1)

    def test_collects_failing_url(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        ydl.extract_info.side_effect = Exception("video unavailable")
        with redirect_stdout(io.StringIO()):
            failed = yt_to_mp3.download(["bad"], "out", 192, False)
        self.assertEqual(failed, ["bad"])

    def test_one_failure_does_not_abort_the_batch(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        ydl.extract_info.side_effect = [
            {"title": "ok1"},
            Exception("410 Gone"),
            {"title": "ok2"},
        ]
        with redirect_stdout(io.StringIO()):
            failed = yt_to_mp3.download(["a", "bad", "c"], "out", 192, False)
        self.assertEqual(failed, ["bad"])
        self.assertEqual(ydl.extract_info.call_count, 3)

    def test_reports_error_text_to_user(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        ydl.extract_info.side_effect = Exception("Private video")
        buf = io.StringIO()
        with redirect_stdout(buf):
            yt_to_mp3.download(["bad"], "out", 192, False)
        self.assertIn("Private video", buf.getvalue())

    def test_prints_saved_title(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        ydl.extract_info.return_value = {"title": "Track Name"}
        buf = io.StringIO()
        with redirect_stdout(buf):
            yt_to_mp3.download(["u"], "out", 192, False)
        self.assertIn("Track Name.mp3", buf.getvalue())

    def test_falls_back_when_title_absent(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        ydl.extract_info.return_value = {}
        buf = io.StringIO()
        with redirect_stdout(buf):
            yt_to_mp3.download(["u"], "out", 192, False)
        self.assertIn("unknown.mp3", buf.getvalue())

    def test_empty_url_list_is_a_no_op(self, mock_cls):
        ydl = make_ydl_mock(mock_cls)
        with redirect_stdout(io.StringIO()):
            failed = yt_to_mp3.download([], "out", 192, False)
        self.assertEqual(failed, [])
        ydl.extract_info.assert_not_called()


@patch("yt_to_mp3.shutil.which", return_value="C:/ffmpeg/bin/ffmpeg.exe")
@patch("yt_to_mp3.download", return_value=[])
class TestMain(unittest.TestCase):

    def run_main(self, argv):
        with patch.object(yt_to_mp3.sys, "argv", ["yt_to_mp3.py"] + argv):
            with redirect_stdout(io.StringIO()):
                yt_to_mp3.main()

    def run_main_expecting_argparse_error(self, argv):
        with patch.object(yt_to_mp3.sys, "stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                self.run_main(argv)
        return ctx.exception

    def test_defaults(self, mock_download, _which):
        self.run_main(["URL"])
        mock_download.assert_called_once_with(["URL"], "downloads", 192, False)

    def test_accepts_multiple_urls(self, mock_download, _which):
        self.run_main(["U1", "U2", "U3"])
        self.assertEqual(mock_download.call_args[0][0], ["U1", "U2", "U3"])

    def test_output_flag(self, mock_download, _which):
        self.run_main(["URL", "-o", "D:/Music"])
        self.assertEqual(mock_download.call_args[0][1], "D:/Music")

    def test_quality_flag_parsed_as_int(self, mock_download, _which):
        self.run_main(["URL", "-q", "320"])
        quality = mock_download.call_args[0][2]
        self.assertEqual(quality, 320)
        self.assertIsInstance(quality, int)

    def test_playlist_flag(self, mock_download, _which):
        self.run_main(["URL", "--playlist"])
        self.assertTrue(mock_download.call_args[0][3])

    def test_rejects_unsupported_bitrate(self, mock_download, _which):
        exc = self.run_main_expecting_argparse_error(["URL", "-q", "999"])
        self.assertEqual(exc.code, 2)
        mock_download.assert_not_called()

    def test_requires_at_least_one_url(self, mock_download, _which):
        self.run_main_expecting_argparse_error([])
        mock_download.assert_not_called()

    def test_exits_when_ffmpeg_missing(self, mock_download, mock_which):
        mock_which.return_value = None
        with self.assertRaises(SystemExit) as ctx:
            self.run_main(["URL"])
        self.assertIn("ffmpeg", str(ctx.exception.code))
        mock_download.assert_not_called()

    def test_ffmpeg_checked_before_downloading(self, mock_download, mock_which):
        self.run_main(["URL"])
        mock_which.assert_called_once_with("ffmpeg")

    def test_success_exits_normally(self, mock_download, _which):
        self.run_main(["URL"])  # no SystemExit -> exit code 0

    def test_exit_code_1_when_a_url_failed(self, mock_download, _which):
        mock_download.return_value = ["bad-url"]
        with self.assertRaises(SystemExit) as ctx:
            self.run_main(["bad-url"])
        self.assertEqual(ctx.exception.code, 1)

    def test_failed_urls_are_listed(self, mock_download, _which):
        mock_download.return_value = ["bad-url"]
        buf = io.StringIO()
        with patch.object(yt_to_mp3.sys, "argv", ["yt_to_mp3.py", "bad-url"]):
            with redirect_stdout(buf), self.assertRaises(SystemExit):
                yt_to_mp3.main()
        self.assertIn("bad-url", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
