"""Tkinter front-end for yt_to_mp3.py.

Run:
    python yt_to_mp3_gui.py

The downloading itself stays in yt_to_mp3.py; this module only adds the
window, runs the work on a background thread and pipes progress back through
a queue, because Tk widgets may only be touched from the main thread.
"""

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


class Cancelled(Exception):
    """Raised inside the progress hook to abort the running download."""


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

        self.outdir = tk.StringVar(value=DEFAULT_OUTDIR)
        self.quality = tk.StringVar(value="192")
        self.playlist = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Готов к работе")

        self._build()
        self.after(80, self._drain_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if shutil.which("ffmpeg") is None:
            self._log("ffmpeg не найден в PATH — конвертация в mp3 не заработает.", "err")
            self._log("Установите его: winget install Gyan.FFmpeg", "muted")

    # ---------------------------------------------------------------- layout

    def _build(self):
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass

        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)   # поле ссылок
        root.rowconfigure(9, weight=2)   # журнал

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="YouTube → MP3",
                  font=("Segoe UI Semibold", 16)).pack(anchor="w")
        ttk.Label(header, text="Скачивание аудиодорожки и конвертация в MP3 с тегами",
                  foreground="#666").pack(anchor="w", pady=(0, 10))

        ttk.Label(root, text="Ссылки (по одной в строке):").grid(
            row=1, column=0, sticky="w")
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
        ttk.Label(folder, text="Папка:").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(folder, textvariable=self.outdir).grid(row=0, column=1, sticky="ew")
        ttk.Button(folder, text="Обзор…", command=self._pick_folder,
                   width=10).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(folder, text="Открыть", command=self._open_outdir,
                   width=10).grid(row=0, column=3, padx=(6, 0))

        opts = ttk.Frame(root)
        opts.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(opts, text="Качество:").grid(row=0, column=0, padx=(0, 8))
        ttk.Combobox(opts, textvariable=self.quality, values=QUALITIES, width=6,
                     state="readonly").grid(row=0, column=1)
        ttk.Label(opts, text="kbps").grid(row=0, column=2, padx=(6, 24))
        ttk.Checkbutton(opts, text="Скачать плейлист целиком",
                        variable=self.playlist).grid(row=0, column=3)

        actions = ttk.Frame(root)
        actions.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(2, weight=1)
        self.btn_start = ttk.Button(actions, text="Скачать",
                                    command=self._start, width=14)
        self.btn_start.grid(row=0, column=0)
        self.btn_cancel = ttk.Button(actions, text="Отмена",
                                     command=self._request_cancel, width=12,
                                     state="disabled")
        self.btn_cancel.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(actions, textvariable=self.status, foreground="#444").grid(
            row=0, column=2, sticky="e")

        self.progress = ttk.Progressbar(root, maximum=100)
        self.progress.grid(row=6, column=0, sticky="ew", pady=(10, 0))

        ttk.Separator(root).grid(row=7, column=0, sticky="ew", pady=14)

        ttk.Label(root, text="Журнал:").grid(row=8, column=0, sticky="w")
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

    # ------------------------------------------------------------- callbacks

    def _pick_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.outdir.get() or HERE)
        if chosen:
            self.outdir.set(os.path.normpath(chosen))

    def _open_outdir(self):
        path = self.outdir.get().strip() or DEFAULT_OUTDIR
        if not os.path.isdir(path):
            messagebox.showinfo("Папка", "Папка ещё не создана.")
            return
        open_folder(path)

    def _start(self):
        urls = [u.strip() for u in self.urls.get("1.0", "end").splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning("Нет ссылок",
                                   "Вставьте хотя бы одну ссылку YouTube.")
            return
        if shutil.which("ffmpeg") is None:
            messagebox.showerror("ffmpeg", "ffmpeg не найден в PATH.\n"
                                           "Установите: winget install Gyan.FFmpeg")
            return

        outdir = self.outdir.get().strip() or DEFAULT_OUTDIR
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Папка", f"Не удалось создать папку:\n{e}")
            return

        self.cancel.clear()
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress["value"] = 0
        self._log(f"Задание: {len(urls)} ссылок → {outdir} "
                  f"({self.quality.get()} kbps)", "muted")

        self.worker = threading.Thread(
            target=self._run,
            args=(urls, outdir, int(self.quality.get()), self.playlist.get()),
            daemon=True,
        )
        self.worker.start()

    def _request_cancel(self):
        self.cancel.set()
        self.btn_cancel.configure(state="disabled")
        self.status.set("Отмена…")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel("Выход",
                                          "Скачивание ещё идёт. Закрыть?"):
                return
            self.cancel.set()
        self.destroy()

    # ---------------------------------------------------------------- worker

    def _run(self, urls, outdir, quality, playlist):
        """Runs on the background thread: never touches a widget directly."""
        failed = []
        total = len(urls)
        for index, url in enumerate(urls, 1):
            if self.cancel.is_set():
                break
            self.queue.put(("status", f"{index} из {total}"))
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
            raise Cancelled("отменено пользователем")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total:
                self.queue.put(("progress", done * 100 / total))
            speed = (d.get("_speed_str") or "").strip()
            eta = (d.get("_eta_str") or "").strip()
            self.queue.put(("status", f"Загрузка {speed}   осталось {eta}"))
        elif d["status"] == "finished":
            self.queue.put(("progress", 100))
            self.queue.put(("status", "Конвертация в mp3…"))

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
                    self.status.set(msg[1])
                elif kind == "done":
                    self._finish(*msg[1:])
        except queue.Empty:
            pass
        self.after(80, self._drain_queue)

    def _finish(self, failed, total, outdir):
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self.progress["value"] = 0

        if self.cancel.is_set():
            self.status.set("Отменено")
            self._log("Отменено пользователем.", "muted")
            return

        ok = total - len(failed)
        self.status.set(f"Готово: {ok} из {total}")
        self._log(f"Готово. Файлы в: {outdir}", "ok")
        if failed:
            self._log("Не удалось скачать:", "err")
            for url in failed:
                self._log(f"  - {url}", "err")

    def _log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
