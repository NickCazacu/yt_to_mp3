"""Tkinter front-end for yt_to_mp3.py.

Run:
    python yt_to_mp3_gui.py

The downloading itself stays in yt_to_mp3.py; this module only adds the
window, runs the work on a background thread and pipes progress back through
a queue, because Tk widgets may only be touched from the main thread.

Every visible string lives in TEXT below and is looked up by key, so the
language selector can re-label the whole window at runtime. The chosen
language is remembered in a small JSON file (see config_path).
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import yt_to_mp3

QUALITIES = ["64", "128", "192", "256", "320"]
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTDIR = os.path.join(HERE, "downloads")
APP_NAME = "yt_to_mp3"

# display name -> code, in the order they appear in the selector
LANGUAGES = {"Русский": "ru", "English": "en"}
DEFAULT_LANGUAGE = "ru"

TEXT = {
    "ru": {
        "subtitle": "Скачивание аудиодорожки и конвертация в MP3 с тегами",
        "urls_label": "Ссылки (по одной в строке):",
        "folder": "Папка:",
        "browse": "Обзор…",
        "open": "Открыть",
        "quality": "Качество:",
        "kbps": "kbps",
        "playlist": "Скачать плейлист целиком",
        "download": "Скачать",
        "cancel": "Отмена",
        "log_label": "Журнал:",
        "ready": "Готов к работе",
        "item_of": "{index} из {total}",
        "downloading": "Загрузка {speed}   осталось {eta}",
        "converting": "Конвертация в mp3…",
        "cancelling": "Отмена…",
        "cancelled": "Отменено",
        "cancelled_log": "Отменено пользователем.",
        "done_status": "Готово: {ok} из {total}",
        "done_log": "Готово. Файлы в: {outdir}",
        "failed_header": "Не удалось скачать:",
        "job": "Задание: {count} ссылок → {outdir} ({quality} kbps)",
        "no_urls_title": "Нет ссылок",
        "no_urls_msg": "Вставьте хотя бы одну ссылку YouTube.",
        "folder_title": "Папка",
        "folder_missing": "Папка ещё не создана.",
        "folder_failed": "Не удалось создать папку:\n{error}",
        "ffmpeg_title": "ffmpeg",
        "ffmpeg_msg": "ffmpeg не найден в PATH.\n"
                      "Установите: winget install Gyan.FFmpeg",
        "ffmpeg_log": "ffmpeg не найден в PATH — конвертация в mp3 не заработает.",
        "ffmpeg_hint": "Установите его: winget install Gyan.FFmpeg",
        "exit_title": "Выход",
        "exit_msg": "Скачивание ещё идёт. Закрыть?",
    },
    "en": {
        "subtitle": "Download the audio track and convert it to tagged MP3",
        "urls_label": "Links (one per line):",
        "folder": "Folder:",
        "browse": "Browse…",
        "open": "Open",
        "quality": "Quality:",
        "kbps": "kbps",
        "playlist": "Download the whole playlist",
        "download": "Download",
        "cancel": "Cancel",
        "log_label": "Log:",
        "ready": "Ready",
        "item_of": "{index} of {total}",
        "downloading": "Downloading {speed}   {eta} left",
        "converting": "Converting to mp3…",
        "cancelling": "Cancelling…",
        "cancelled": "Cancelled",
        "cancelled_log": "Cancelled by the user.",
        "done_status": "Done: {ok} of {total}",
        "done_log": "Done. Files are in: {outdir}",
        "failed_header": "Could not download:",
        "job": "Job: {count} links → {outdir} ({quality} kbps)",
        "no_urls_title": "No links",
        "no_urls_msg": "Paste at least one YouTube link.",
        "folder_title": "Folder",
        "folder_missing": "The folder does not exist yet.",
        "folder_failed": "Could not create the folder:\n{error}",
        "ffmpeg_title": "ffmpeg",
        "ffmpeg_msg": "ffmpeg was not found on PATH.\n"
                      "Install it: winget install Gyan.FFmpeg",
        "ffmpeg_log": "ffmpeg was not found on PATH — mp3 conversion will fail.",
        "ffmpeg_hint": "Install it: winget install Gyan.FFmpeg",
        "exit_title": "Quit",
        "exit_msg": "A download is still running. Close anyway?",
    },
}


class Cancelled(Exception):
    """Raised inside the progress hook to abort the running download."""


def config_path():
    """Where the chosen language is remembered, per user and per platform."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = (os.environ.get("XDG_CONFIG_HOME")
                or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, APP_NAME, "settings.json")


def load_settings(path=None):
    """Read the settings file; a missing or broken one is simply no settings."""
    try:
        with open(path or config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data, path=None):
    """Best-effort write: a read-only home must not break the app."""
    path = path or config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def open_folder(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - user-initiated, path is ours
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube → MP3")
        self.minsize(680, 620)

        self.queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self._pump = None          # id of the pending _drain_queue timer

        self.settings = load_settings()
        remembered = self.settings.get("language")
        self.lang = remembered if remembered in TEXT else DEFAULT_LANGUAGE
        self._labels = {}          # widget -> text key, for re-labelling
        self._status = ("ready", {})

        self.language = tk.StringVar(
            value=next(n for n, c in LANGUAGES.items() if c == self.lang))
        self.outdir = tk.StringVar(value=DEFAULT_OUTDIR)
        self.quality = tk.StringVar(value="192")
        self.playlist = tk.BooleanVar(value=False)
        self.status = tk.StringVar()

        self._build()
        self._pump = self.after(80, self._drain_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if shutil.which("ffmpeg") is None:
            self._log(self.t("ffmpeg_log"), "err")
            self._log(self.t("ffmpeg_hint"), "muted")

    # ----------------------------------------------------------- translation

    def t(self, key, **params):
        text = TEXT[self.lang][key]
        return text.format(**params) if params else text

    def _track(self, widget, key):
        """Remember a widget so _on_language_change can re-label it."""
        self._labels[widget] = key
        return widget

    def _retranslate(self):
        for widget, key in self._labels.items():
            widget.configure(text=self.t(key))
        self._render_status()

    def _on_language_change(self, _event=None):
        self.lang = LANGUAGES[self.language.get()]
        self._retranslate()
        self.settings["language"] = self.lang
        save_settings(self.settings)

    # ---------------------------------------------------------------- layout

    def _build(self):
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass

        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)   # поле ссылок / links field
        root.rowconfigure(9, weight=2)   # журнал / log

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="YouTube → MP3",
                  font=("Segoe UI Semibold", 16)).grid(row=0, column=0, sticky="w")
        self._track(ttk.Label(header, foreground="#666"), "subtitle").grid(
            row=1, column=0, sticky="w", pady=(0, 10))
        lang_box = ttk.Combobox(header, textvariable=self.language,
                                values=list(LANGUAGES), width=10, state="readonly")
        lang_box.grid(row=0, column=1, rowspan=2, sticky="ne")
        lang_box.bind("<<ComboboxSelected>>", self._on_language_change)

        self._track(ttk.Label(root), "urls_label").grid(row=1, column=0, sticky="w")
        urls_box = ttk.Frame(root)
        urls_box.grid(row=2, column=0, sticky="nsew", pady=(4, 10))
        urls_box.columnconfigure(0, weight=1)
        urls_box.rowconfigure(0, weight=1)
        self.urls = tk.Text(urls_box, height=5, wrap="none", font=("Consolas", 10),
                            relief="solid", borderwidth=1)
        self.urls.grid(row=0, column=0, sticky="nsew")
        urls_scroll = ttk.Scrollbar(urls_box, command=self.urls.yview)
        urls_scroll.grid(row=0, column=1, sticky="ns")
        self.urls.configure(yscrollcommand=urls_scroll.set)

        folder = ttk.Frame(root)
        folder.grid(row=3, column=0, sticky="ew")
        folder.columnconfigure(1, weight=1)
        self._track(ttk.Label(folder), "folder").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(folder, textvariable=self.outdir).grid(row=0, column=1, sticky="ew")
        self._track(ttk.Button(folder, command=self._pick_folder, width=10),
                    "browse").grid(row=0, column=2, padx=(8, 0))
        self._track(ttk.Button(folder, command=self._open_outdir, width=10),
                    "open").grid(row=0, column=3, padx=(6, 0))

        opts = ttk.Frame(root)
        opts.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self._track(ttk.Label(opts), "quality").grid(row=0, column=0, padx=(0, 8))
        ttk.Combobox(opts, textvariable=self.quality, values=QUALITIES, width=6,
                     state="readonly").grid(row=0, column=1)
        self._track(ttk.Label(opts), "kbps").grid(row=0, column=2, padx=(6, 24))
        self._track(ttk.Checkbutton(opts, variable=self.playlist),
                    "playlist").grid(row=0, column=3)

        actions = ttk.Frame(root)
        actions.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(2, weight=1)
        self.btn_start = self._track(
            ttk.Button(actions, command=self._start, width=14), "download")
        self.btn_start.grid(row=0, column=0)
        self.btn_cancel = self._track(
            ttk.Button(actions, command=self._request_cancel, width=12,
                       state="disabled"), "cancel")
        self.btn_cancel.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(actions, textvariable=self.status, foreground="#444").grid(
            row=0, column=2, sticky="e")

        self.progress = ttk.Progressbar(root, maximum=100)
        self.progress.grid(row=6, column=0, sticky="ew", pady=(10, 0))

        ttk.Separator(root).grid(row=7, column=0, sticky="ew", pady=14)

        self._track(ttk.Label(root), "log_label").grid(row=8, column=0, sticky="w")
        log_box = ttk.Frame(root)
        log_box.grid(row=9, column=0, sticky="nsew", pady=(4, 0))
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, height=10, wrap="word", font=("Consolas", 9),
                           state="disabled", relief="solid", borderwidth=1,
                           background="#fafafa")
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_box, command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.tag_configure("err", foreground="#c0392b")
        self.log.tag_configure("ok", foreground="#1e7a34")
        self.log.tag_configure("muted", foreground="#777")

        self._retranslate()   # label everything without rewriting the settings

    # ------------------------------------------------------------- callbacks

    def _pick_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.outdir.get() or HERE)
        if chosen:
            self.outdir.set(os.path.normpath(chosen))

    def _open_outdir(self):
        path = self.outdir.get().strip() or DEFAULT_OUTDIR
        if not os.path.isdir(path):
            messagebox.showinfo(self.t("folder_title"), self.t("folder_missing"))
            return
        open_folder(path)

    def _start(self):
        urls = [u.strip() for u in self.urls.get("1.0", "end").splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning(self.t("no_urls_title"), self.t("no_urls_msg"))
            return
        if shutil.which("ffmpeg") is None:
            messagebox.showerror(self.t("ffmpeg_title"), self.t("ffmpeg_msg"))
            return

        outdir = self.outdir.get().strip() or DEFAULT_OUTDIR
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            messagebox.showerror(self.t("folder_title"),
                                 self.t("folder_failed", error=e))
            return

        self.cancel.clear()
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress["value"] = 0
        self._log(self.t("job", count=len(urls), outdir=outdir,
                         quality=self.quality.get()), "muted")

        self.worker = threading.Thread(
            target=self._run,
            args=(urls, outdir, int(self.quality.get()), self.playlist.get()),
            daemon=True,
        )
        self.worker.start()

    def _request_cancel(self):
        self.cancel.set()
        self.btn_cancel.configure(state="disabled")
        self._set_status("cancelling")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel(self.t("exit_title"), self.t("exit_msg")):
                return
            self.cancel.set()
        if self._pump is not None:
            self.after_cancel(self._pump)   # no timer firing into a dead window
            self._pump = None
        self.destroy()

    # ---------------------------------------------------------------- worker

    def _run(self, urls, outdir, quality, playlist):
        """Runs on the background thread: never touches a widget directly."""
        failed = []
        total = len(urls)
        for index, url in enumerate(urls, 1):
            if self.cancel.is_set():
                break
            self.queue.put(("status", "item_of", {"index": index, "total": total}))
            self.queue.put(("progress", 0))
            failed += yt_to_mp3.download(
                [url], outdir, quality, playlist,
                hook=self._hook,
                log=lambda text: self.queue.put(("log", text.strip("\n"))),
            )
        self.queue.put(("done", failed, total, outdir))

    def _hook(self, d):
        """yt-dlp progress callback (background thread)."""
        if self.cancel.is_set():
            raise Cancelled("cancelled by the user")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total:
                self.queue.put(("progress", done * 100 / total))
            self.queue.put(("status", "downloading", {
                "speed": (d.get("_speed_str") or "").strip(),
                "eta": (d.get("_eta_str") or "").strip(),
            }))
        elif d["status"] == "finished":
            self.queue.put(("progress", 100))
            self.queue.put(("status", "converting", {}))

    # ------------------------------------------------------------ ui pumping

    def _drain_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    text = msg[1]
                    if "FAILED" in text:
                        tag = "err"
                    elif "saved:" in text:
                        tag = "ok"
                    else:
                        tag = None
                    self._log(text, tag)
                elif kind == "progress":
                    self.progress["value"] = msg[1]
                elif kind == "status":
                    self._set_status(msg[1], **msg[2])
                elif kind == "done":
                    self._finish(*msg[1:])
        except queue.Empty:
            pass
        self._pump = self.after(80, self._drain_queue)

    def _finish(self, failed, total, outdir):
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self.progress["value"] = 0

        if self.cancel.is_set():
            self._set_status("cancelled")
            self._log(self.t("cancelled_log"), "muted")
            return

        self._set_status("done_status", ok=total - len(failed), total=total)
        self._log(self.t("done_log", outdir=outdir), "ok")
        if failed:
            self._log(self.t("failed_header"), "err")
            for url in failed:
                self._log(f"  - {url}", "err")

    # ---------------------------------------------------------------- output

    def _set_status(self, key, **params):
        """Keep the key so the text can be rebuilt when the language changes."""
        self._status = (key, params)
        self._render_status()

    def _render_status(self):
        key, params = self._status
        self.status.set(self.t(key, **params))

    def _log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
