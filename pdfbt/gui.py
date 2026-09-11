"""Tkinter desktop UI: open an English PDF, read it side-by-side with Chinese."""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

from .exporter import export_html, export_pdf
from .pdf_reader import Paragraph, extract_paragraphs, page_count
from .translator import Translator, available_providers

TARGETS = [("简体中文", "zh-CN"), ("繁體中文", "zh-TW")]
CJK_FONTS = {
    "win32": "Microsoft YaHei",
    "darwin": "PingFang SC",
}


def _cjk_font(root: tk.Misc) -> str:
    preferred = CJK_FONTS.get(sys.platform, "Noto Sans CJK SC")
    families = set(tkfont.families(root))
    for name in (preferred, "Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimSun"):
        if not families or name in families:
            return name
    return "TkDefaultFont"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PDF 中英对照翻译 / Bilingual PDF Translator")
        self.geometry("1280x820")
        self.minsize(900, 560)

        self.pdf_path: str | None = None
        self.paragraphs: list[Paragraph] = []
        self.translations: list[str] = []
        self._events: queue.Queue = queue.Queue()
        self._total = 0
        self._done = 0
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

        self._build_toolbar()
        self._build_panes()
        self._build_statusbar()
        self.after(100, self._drain_events)

    # ---------------------------------------------------------------- layout
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")

        ttk.Button(bar, text="打开 PDF", command=self.open_pdf).pack(side="left")
        self.file_label = ttk.Label(bar, text="未选择文件", width=30)
        self.file_label.pack(side="left", padx=(8, 16))

        ttk.Label(bar, text="页码").pack(side="left")
        self.first_page = tk.StringVar(value="1")
        self.last_page = tk.StringVar(value="")
        ttk.Entry(bar, textvariable=self.first_page, width=5).pack(side="left", padx=4)
        ttk.Label(bar, text="到").pack(side="left")
        ttk.Entry(bar, textvariable=self.last_page, width=5).pack(side="left", padx=4)

        ttk.Label(bar, text="引擎").pack(side="left", padx=(16, 4))
        self.provider = tk.StringVar(value="google")
        ttk.Combobox(
            bar, textvariable=self.provider, values=list(available_providers()),
            width=10, state="readonly",
        ).pack(side="left")

        ttk.Label(bar, text="译文").pack(side="left", padx=(16, 4))
        self.target_label = tk.StringVar(value=TARGETS[0][0])
        ttk.Combobox(
            bar, textvariable=self.target_label, values=[name for name, _ in TARGETS],
            width=9, state="readonly",
        ).pack(side="left")

        self.translate_button = ttk.Button(bar, text="开始翻译", command=self.start_translation)
        self.translate_button.pack(side="left", padx=(16, 4))
        self.stop_button = ttk.Button(bar, text="停止", command=self.stop_translation, state="disabled")
        self.stop_button.pack(side="left")

        ttk.Button(bar, text="导出 PDF", command=lambda: self.export("pdf")).pack(side="right")
        ttk.Button(bar, text="导出 HTML", command=lambda: self.export("html")).pack(side="right", padx=6)

    def _build_panes(self) -> None:
        frame = ttk.Frame(self, padding=(10, 0))
        frame.pack(fill="both", expand=True)

        self.left = tk.Text(frame, wrap="word", font=("Georgia", 12), padx=12, pady=10,
                            spacing3=4, background="#ffffff", borderwidth=1, relief="solid")
        self.right = tk.Text(frame, wrap="word", font=(_cjk_font(self), 12), padx=12, pady=10,
                             spacing3=4, background="#fbfbfd", borderwidth=1, relief="solid")
        self.scroll = ttk.Scrollbar(frame, orient="vertical", command=self._on_scrollbar)

        self.left.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.right.pack(side="right", fill="both", expand=True, padx=(8, 4))

        for widget in (self.left, self.right):
            widget.configure(yscrollcommand=self._on_textscroll)
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Button-4>", self._on_wheel)
            widget.bind("<Button-5>", self._on_wheel)
            widget.tag_configure("page", foreground="#999999", spacing1=10, spacing3=6)
            widget.tag_configure("pending", foreground="#b0b0b0")
            widget.tag_configure("error", foreground="#c0392b")
        self.right.tag_configure("zh", foreground="#0b4f9e")

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(10, 6))
        bar.pack(fill="x")
        self.progress = ttk.Progressbar(bar, mode="determinate", length=260)
        self.progress.pack(side="left")
        self.status = tk.StringVar(value="打开一个英文 PDF 开始。")
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=12)

    # --------------------------------------------------------------- scroll
    def _on_scrollbar(self, *args) -> None:
        self.left.yview(*args)
        self.right.yview(*args)

    def _on_textscroll(self, first, last) -> None:
        self.scroll.set(first, last)
        for widget in (self.left, self.right):
            if widget.yview()[0] != float(first):
                widget.yview_moveto(first)

    def _on_wheel(self, event) -> str:
        delta = -1 if getattr(event, "num", None) == 4 else 1 if getattr(event, "num", None) == 5 else 0
        if delta == 0:
            delta = -1 if event.delta > 0 else 1
        self.left.yview_scroll(delta * 3, "units")
        self.right.yview_scroll(delta * 3, "units")
        return "break"

    # ----------------------------------------------------------------- data
    def open_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 PDF", filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")]
        )
        if not path:
            return
        try:
            total = page_count(path)
            paragraphs = extract_paragraphs(path)
        except Exception as exc:  # noqa: BLE001 - surfaced in a dialog
            messagebox.showerror("无法读取 PDF", str(exc))
            return
        if not paragraphs:
            messagebox.showwarning(
                "没有文本", "这个 PDF 里没有可提取的文字，可能是扫描件（需要 OCR）。"
            )
            return
        self.pdf_path = path
        self.paragraphs = paragraphs
        self.translations = [""] * len(paragraphs)
        self.file_label.configure(text=os.path.basename(path))
        self.first_page.set("1")
        self.last_page.set(str(total))
        self._render_source()
        self.status.set(f"{total} 页，{len(paragraphs)} 个段落。点击“开始翻译”。")

    def _selected_range(self) -> tuple[int, int]:
        def parse(value: str, default: int) -> int:
            try:
                return max(1, int(value.strip()))
            except ValueError:
                return default

        pages = [p.page for p in self.paragraphs] or [1]
        first = parse(self.first_page.get(), min(pages))
        last = parse(self.last_page.get(), max(pages))
        return first, max(first, last)

    def _active_paragraphs(self) -> list[int]:
        first, last = self._selected_range()
        return [i for i, p in enumerate(self.paragraphs) if first <= p.page <= last]

    @staticmethod
    def _mark(side: str, index: int, kind: str) -> str:
        return f"{side}{index}{kind}"

    def _render_source(self) -> None:
        """Fill both panes; marks (not indices) track paragraph boundaries."""
        for widget in (self.left, self.right):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            for name in widget.mark_names():
                if name not in ("insert", "current", "anchor"):
                    widget.mark_unset(name)
        last_page = None
        for i in self._active_paragraphs():
            para = self.paragraphs[i]
            if para.page != last_page:
                for widget in (self.left, self.right):
                    widget.insert("end", f"—— 第 {para.page} 页 ——\n", "page")
                last_page = para.page
            for widget, side, body, tags in (
                (self.left, "L", para.text, ()),
                (self.right, "R", "…", ("pending",)),
            ):
                start = widget.index("end-1c")
                widget.mark_set(self._mark(side, i, "s"), start)
                widget.mark_gravity(self._mark(side, i, "s"), "left")
                widget.insert("end", body, tags)
                widget.mark_set(self._mark(side, i, "p"), "end-1c")
                widget.mark_gravity(self._mark(side, i, "p"), "left")
                widget.insert("end", "\n\n")
                widget.mark_set(self._mark(side, i, "e"), "end-1c")
                widget.mark_gravity(self._mark(side, i, "e"), "left")
        self._balance()

    def _clear_padding(self, indices: list[int]) -> None:
        """Drop blank lines added by an earlier balance pass so padding never accumulates."""
        for widget, side in ((self.left, "L"), (self.right, "R")):
            names = widget.mark_names()
            for i in indices:
                pad = self._mark(side, i, "p")
                if pad not in names:
                    continue
                end = f"{self._mark(side, i, 'e')} - 2c"
                if widget.compare(pad, "<", end):
                    widget.delete(pad, end)

    def _balance(self) -> None:
        """Pad the shorter side so paragraph pairs stay visually aligned."""
        for widget in (self.left, self.right):
            widget.configure(state="normal")
        indices = self._active_paragraphs()
        self._clear_padding(indices)
        self.update_idletasks()
        for position, i in enumerate(indices):
            nxt = indices[position + 1] if position + 1 < len(indices) else None
            left_end = self._mark("L", nxt, "s") if nxt is not None else "end-1c"
            right_end = self._mark("R", nxt, "s") if nxt is not None else "end-1c"
            left_lines = self.left.count(self._mark("L", i, "s"), left_end, "displaylines")[0]
            right_lines = self.right.count(self._mark("R", i, "s"), right_end, "displaylines")[0]
            if left_lines > right_lines:
                self.right.insert(self._mark("R", i, "p"), "\n" * (left_lines - right_lines))
            elif right_lines > left_lines:
                self.left.insert(self._mark("L", i, "p"), "\n" * (right_lines - left_lines))
            self.update_idletasks()
        for widget in (self.left, self.right):
            widget.configure(state="disabled")

    # ------------------------------------------------------------ translate
    def start_translation(self) -> None:
        if not self.paragraphs:
            messagebox.showinfo("请先打开 PDF", "先选择一个 PDF 文件。")
            return
        if self._worker and self._worker.is_alive():
            return
        indices = self._active_paragraphs()
        if not indices:
            messagebox.showinfo("范围为空", "选择的页码范围内没有文字。")
            return
        target = dict(TARGETS)[self.target_label.get()]
        translator = Translator(provider=self.provider.get(), target=target)
        self._stop.clear()
        self.translate_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._total = len(indices)
        self._done = 0
        self.progress.configure(maximum=len(indices), value=0)
        self.status.set(f"翻译中 0/{len(indices)} …")
        self._render_source()

        def run() -> None:
            texts = [self.paragraphs[i].text for i in indices]

            def on_result(pos: int, text: str, error: str | None) -> None:
                self._events.put(("result", indices[pos], text, error))

            translator.translate_many(texts, on_result=on_result, should_stop=self._stop.is_set)
            self._events.put(("done", len(indices), "", None))

        self._worker = threading.Thread(target=run, daemon=True)
        self._worker.start()

    def stop_translation(self) -> None:
        self._stop.set()
        self.status.set("正在停止…")

    def _drain_events(self) -> None:
        dirty = False
        while True:
            try:
                kind, index, text, error = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "result":
                self.translations[index] = text
                self._apply_result(index, text, error)
                self._done += 1
                self.progress.configure(value=self._done)
                dirty = True
            elif kind == "done":
                self.translate_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                translated = sum(1 for t in self.translations if t)
                self._balance()
                self.status.set(f"完成：{translated}/{index} 段已翻译。")
                dirty = False
        if dirty:
            self.status.set(f"翻译中 {self._done}/{self._total} …")
        self.after(120, self._drain_events)

    def _apply_result(self, index: int, text: str, error: str | None) -> None:
        start = self._mark("R", index, "s")
        pad = self._mark("R", index, "p")
        if start not in self.right.mark_names():
            return
        body = text or f"[翻译失败] {error}"
        self.right.configure(state="normal")
        self.right.delete(start, pad)
        self.right.insert(start, body, "zh" if text else "error")
        self.right.mark_set(pad, f"{start} + {len(body)}c")
        self.right.mark_gravity(pad, "left")
        self.right.configure(state="disabled")

    # --------------------------------------------------------------- export
    def export(self, kind: str) -> None:
        if not any(self.translations):
            messagebox.showinfo("没有译文", "先翻译再导出。")
            return
        default = os.path.splitext(os.path.basename(self.pdf_path or "output"))[0] + f"_bilingual.{kind}"
        path = filedialog.asksaveasfilename(defaultextension=f".{kind}", initialfile=default)
        if not path:
            return
        pairs = [
            (self.paragraphs[i].page, self.paragraphs[i].text, self.translations[i])
            for i in self._active_paragraphs()
            if self.translations[i]
        ]
        title = os.path.basename(self.pdf_path or "document")
        try:
            if kind == "html":
                export_html(path, title, pairs)
            else:
                export_pdf(path, title, pairs, target=dict(TARGETS)[self.target_label.get()])
        except Exception as exc:  # noqa: BLE001 - surfaced in a dialog
            messagebox.showerror("导出失败", str(exc))
            return
        self.status.set(f"已导出：{path}")


def main() -> None:
    App().mainloop()
