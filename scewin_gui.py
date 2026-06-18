import os
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

OPTION_RE = re.compile(r"^(\*?)\[(\w+)\]\s*(.*?)\s*$")
KEYVAL_RE = re.compile(r"^([^\t=]+?)\t*=\s*(.*)$")
INNER_RE = re.compile(r"^(.*?)(<[^>]*>|\[[^\]]*\])(.*)$")

HEADER_LINE_COUNT = 6
HEADER_SIGNATURE = "// Script File Name"


def detect_newline(text):
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def split_header(text):
    lines = text.splitlines()
    if len(lines) >= HEADER_LINE_COUNT:
        header_lines = lines[:HEADER_LINE_COUNT]
        rest_text = "\n".join(lines[HEADER_LINE_COUNT:])
        return header_lines, rest_text
    return [], text


def split_comment(s):
    idx = s.find("//")
    if idx == -1:
        return s, None
    return s[:idx], s[idx + 2 :]


# ---------------------------------------------------------- dark theme (blue)
BG = "#1e1f2b"  # основной фон
BG_PANEL = "#262838"  # фон панелей/карточек
BG_ENTRY = "#2d2f42"  # фон полей ввода / списка / текста
FG = "#e3e5ec"  # основной текст
FG_DIM = "#9aa0b4"  # вторичный текст
ACCENT = "#3b82f6"  # синий акцент
ACCENT_HOVER = "#5b9bf8"
ACCENT_ACTIVE = "#2563eb"
BORDER = "#3a3d52"


class Field:
    def __init__(self, key, value, comment):
        self.key = key
        self.value = value
        self.comment = comment


class Record:
    def __init__(self, raw_lines):
        self.raw_lines = raw_lines
        self.fields = []  # list[Field], in original order
        self.options = []  # list[dict] for "Options" blocks
        self.options_comment = None
        self.modified = False
        self._parse()

    # ------------------------------------------------------------ parsing
    def _parse(self):
        for line in self.raw_lines:
            m = KEYVAL_RE.match(line)
            if m:
                key = m.group(1).strip()
                rest = m.group(2)
                if key == "Options":
                    val, comment = split_comment(rest)
                    om = OPTION_RE.match(val.strip())
                    if om:
                        self.options.append(
                            {
                                "marker": om.group(1) == "*",
                                "code": om.group(2),
                                "desc": om.group(3).strip(),
                                "comment": comment,
                                "indent": "",
                            }
                        )
                    self.fields.append(Field(key, "", None))
                else:
                    value, comment = split_comment(rest)
                    self.fields.append(Field(key, value.rstrip(), comment))
            else:
                stripped = line.strip()
                om = OPTION_RE.match(stripped)
                if om:
                    val, comment = split_comment(om.group(3))
                    indent = line[: len(line) - len(line.lstrip())]
                    self.options.append(
                        {
                            "marker": om.group(1) == "*",
                            "code": om.group(2),
                            "desc": val.strip(),
                            "comment": comment,
                            "indent": indent,
                        }
                    )

    # ------------------------------------------------------------- helpers
    def get(self, key):
        for f in self.fields:
            if f.key == key:
                return f
        return None

    @property
    def name(self):
        f = self.get("Setup Question")
        if f and f.value.strip():
            return f.value.strip()
        return "(без имени)"

    @property
    def has_options(self):
        return len(self.options) > 0

    @property
    def search_text(self):
        parts = []
        for f in self.fields:
            if f.key == "Options":
                continue
            parts.append(f.value)
            if f.comment:
                parts.append(f.comment)
        for opt in self.options:
            parts.append(opt["code"])
            parts.append(opt["desc"])
        return " ".join(parts).lower()

    @property
    def value_field(self):
        return self.get("Value")

    @property
    def bios_default_field(self):
        return self.get("BIOS Default")

    # ------------------------------------------------------------- output
    def to_text(self):
        SPACE_AFTER_EQUALS = {"Setup Question", "Help String"}
        lines = []
        for f in self.fields:
            if f.key == "Options":
                if not self.options:
                    continue
                first = self.options[0]
                marker = "*" if first["marker"] else ""
                line = f"Options\t={marker}[{first['code']}]{first['desc']}"
                if first["comment"] is not None:
                    line += f"\t//{first['comment']}"
                lines.append(line)
                for opt in self.options[1:]:
                    marker = "*" if opt["marker"] else ""
                    indent = opt["indent"] or "\t\t  "
                    oline = f"{indent}{marker}[{opt['code']}]{opt['desc']}"
                    if opt["comment"] is not None:
                        oline += f"\t//{opt['comment']}"
                    lines.append(oline)
            else:
                sep = "= " if f.key in SPACE_AFTER_EQUALS else "="
                line = f"{f.key}\t{sep}{f.value}"
                if f.comment is not None:
                    line += f"\t//{f.comment}"
                lines.append(line)
        return "\n".join(lines)


# ------------------------------------------------------------- file utils
def parse_file(text):
    lines = text.splitlines()
    records = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                records.append(Record(current))
                current = []
        else:
            current.append(line)
    if current:
        records.append(Record(current))
    return records


def read_text_file(path):
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(), "utf-8"


# -------------------------------------------------------------------- GUI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SCEWIN_GUI")
        self.geometry("950x600")

        self.records = []
        self.filtered = []
        self.current_record = None
        self.source_path = None
        self.encoding = "utf-8"
        self.header_lines = []
        self.newline = "\n"

        self._apply_dark_theme()
        self._build_ui()

    # ------------------------------------------------------------- layout
    def _apply_dark_theme(self):
        self.configure(bg=BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=BG,
            foreground=FG,
            fieldbackground=BG_ENTRY,
            bordercolor=BORDER,
            darkcolor=BG_PANEL,
            lightcolor=BG_PANEL,
            troughcolor=BG_ENTRY,
            focuscolor=ACCENT,
        )

        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)

        style.configure("TLabelframe", background=BG, bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT)

        style.configure(
            "TButton",
            background=BG_PANEL,
            foreground=FG,
            bordercolor=BORDER,
            focusthickness=1,
            padding=6,
        )
        style.map(
            "TButton",
            background=[
                ("active", ACCENT_HOVER),
                ("pressed", ACCENT_ACTIVE),
                ("disabled", BG_PANEL),
            ],
            foreground=[("disabled", FG_DIM)],
            bordercolor=[("active", ACCENT), ("focus", ACCENT)],
        )

        style.configure(
            "TEntry",
            fieldbackground=BG_ENTRY,
            foreground=FG,
            insertcolor=FG,
            bordercolor=BORDER,
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)])

        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.map(
            "TCheckbutton",
            background=[("active", BG)],
            indicatorcolor=[("selected", ACCENT), ("!selected", BG_ENTRY)],
        )

        style.configure("TRadiobutton", background=BG, foreground=FG)
        style.map(
            "TRadiobutton",
            background=[("active", BG)],
            indicatorcolor=[("selected", ACCENT), ("!selected", BG_ENTRY)],
        )

        style.configure(
            "Vertical.TScrollbar",
            background=BG_PANEL,
            troughcolor=BG,
            bordercolor=BORDER,
            arrowcolor=FG,
        )
        style.map("Vertical.TScrollbar", background=[("active", ACCENT)])

    def _style_listbox_or_text(self, widget):
        widget.configure(
            bg=BG_ENTRY,
            fg=FG,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            relief=tk.FLAT,
        )
        if isinstance(widget, tk.Text):
            widget.configure(insertbackground=FG)

    def _build_ui(self):
        top = ttk.Frame(self, padding=6)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(top, text="Open File", command=self.open_file).pack(side=tk.LEFT)
        ttk.Button(top, text="Export", command=self.run_scewin_export).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(top, text="Import", command=self.run_scewin_import).pack(
            side=tk.LEFT, padx=4
        )
        self.header_btn = ttk.Button(
            top, text="Header", command=self.show_header, state=tk.DISABLED
        )
        self.header_btn.pack(side=tk.LEFT, padx=4)

        self.include_header_var = tk.BooleanVar(value=True)

        main = ttk.Frame(self, padding=6)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # ----- left: list + filter
        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y)

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self.refresh_list())
        ttk.Label(left, text="Search:").pack(anchor=tk.W)
        ttk.Entry(left, textvariable=self.filter_var, width=40).pack(
            fill=tk.X, pady=(0, 4)
        )

        self.search_scope = tk.StringVar(value="all")
        scope_frame = ttk.Frame(left)
        scope_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Radiobutton(
            scope_frame,
            text="By title",
            value="name",
            variable=self.search_scope,
            command=self.refresh_list,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            scope_frame,
            text="In all fields",
            value="all",
            variable=self.search_scope,
            command=self.refresh_list,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.match_count_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.match_count_var).pack(anchor=tk.W)

        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(list_frame, width=45, exportselection=False)
        self._style_listbox_or_text(self.listbox)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        # ----- right: details
        right_container = ttk.Frame(main, padding=(10, 0, 0, 0))
        right_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_canvas = tk.Canvas(right_container, background=BG, highlightthickness=0)
        right_scrollbar = ttk.Scrollbar(
            right_container, orient=tk.VERTICAL, command=right_canvas.yview
        )
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        right = ttk.Frame(right_canvas)
        right_window_id = right_canvas.create_window((0, 0), window=right, anchor="nw")

        def _on_right_frame_configure(event):
            right_canvas.configure(scrollregion=right_canvas.bbox("all"))

        right.bind("<Configure>", _on_right_frame_configure)

        def _on_right_canvas_configure(event):
            right_canvas.itemconfig(right_window_id, width=event.width)

        right_canvas.bind("<Configure>", _on_right_canvas_configure)

        def _cursor_over_right_panel(event):
            widget_path = str(event.widget)
            canvas_path = str(right_canvas)
            return widget_path == canvas_path or widget_path.startswith(
                canvas_path + "."
            )

        def _on_right_mousewheel(event):
            if _cursor_over_right_panel(event):
                right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.bind_all("<MouseWheel>", _on_right_mousewheel)

        # Linux/X11
        def _on_right_scroll_up(event):
            if _cursor_over_right_panel(event):
                right_canvas.yview_scroll(-1, "units")

        def _on_right_scroll_down(event):
            if _cursor_over_right_panel(event):
                right_canvas.yview_scroll(1, "units")

        self.bind_all("<Button-4>", _on_right_scroll_up)
        self.bind_all("<Button-5>", _on_right_scroll_down)

        info = ttk.LabelFrame(right, text="Параметр", padding=8)
        info.pack(fill=tk.X)

        self.info_vars = {}
        for key in ("Setup Question", "Help String", "Token", "Offset", "Width"):
            row = ttk.Frame(info)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=key + ":", width=16).pack(side=tk.LEFT)
            var = tk.StringVar()
            ttk.Label(row, textvariable=var, wraplength=550, justify=tk.LEFT).pack(
                side=tk.LEFT, fill=tk.X, expand=True
            )
            self.info_vars[key] = var

        # ----- editable area
        self.edit_frame = ttk.LabelFrame(right, text="Change in value", padding=8)
        self.edit_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.placeholder_label = ttk.Label(self.edit_frame, text="Select an option")
        self.placeholder_label.pack(anchor=tk.W)

        # widgets used for "Options" type
        self.options_var = tk.StringVar()
        self.options_radio_frame = ttk.Frame(self.edit_frame)
        self.option_buttons = []

        # widgets used for "Value"/"BIOS Default" type
        self.value_frame = ttk.Frame(self.edit_frame)
        self.value_var = tk.StringVar()
        self.bios_default_var = tk.StringVar()

        bottom = ttk.Frame(right)
        bottom.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(bottom, text="Apply", command=self.apply_change).pack(side=tk.LEFT)
        self.modified_label = ttk.Label(bottom, text="")
        self.modified_label.pack(side=tk.LEFT, padx=10)

        # raw preview
        preview = ttk.LabelFrame(right, text="Block Preview", padding=4)
        preview.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.preview_text = tk.Text(
            preview, height=10, wrap=tk.NONE, font=("Consolas", 9)
        )
        self._style_listbox_or_text(self.preview_text)
        self.preview_text.pack(fill=tk.BOTH, expand=True)
        self.preview_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------- actions
    def open_file(self):
        path = filedialog.askopenfilename(
            title="Select a .txt file containing the settings",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            text, enc = read_text_file(path)
        except Exception as e:
            messagebox.showerror("Error", f"Unable to read the file:\n{e}")
            return
        self._load_text(text, path, enc)

    def _load_text(self, text, source_path, encoding):
        self.newline = detect_newline(text)
        header_lines, body_text = split_header(text)
        self.header_lines = header_lines
        self.records = [r for r in parse_file(body_text) if r.name != "(без имени)"]
        self.encoding = encoding
        self.source_path = source_path
        self.current_record = None
        self.header_btn.config(state=(tk.NORMAL if header_lines else tk.DISABLED))
        self.refresh_list()
        self.clear_details()

    def show_header(self):
        if not self.header_lines:
            messagebox.showinfo("Error", "No header was found in the current file.")
            return
        win = tk.Toplevel(self)
        win.configure(bg=BG)
        win.title("Заголовок файла (первые 5 строк)")
        txt = tk.Text(win, width=80, height=8, font=("Consolas", 9))
        self._style_listbox_or_text(txt)
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        txt.insert("1.0", "\n".join(self.header_lines))
        txt.config(state=tk.DISABLED)
        ttk.Label(
            win,
            text="These lines will be inserted as-is at the beginning "
            "the file being saved.",
        ).pack(padx=8, pady=(0, 8))

    def run_scewin_export(self):
        if os.name != "nt":
            messagebox.showerror("Error", "Exporting via SCEWIN works only on Windows.")
            return

        nvram_name = "nvram.txt"
        log_name = "log.txt"
        for p in (nvram_name, log_name):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

        self.update_idletasks()

        try:
            subprocess.run(
                "SCEWIN_64.exe /O /S nvram.txt 2> log.txt",
                shell=True,
            )
        except subprocess.TimeoutExpired:
            messagebox.showerror(
                "Error", "SCEWIN was not completed within the allotted time."
            )
            return
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start SCEWIN:\n{e}")
            return

        if not os.path.exists(nvram_name):
            extra = ""
            if os.path.exists(log_name):
                try:
                    with open(log_name, "r", errors="replace") as f:
                        extra = f.read().strip()[:800]
                except Exception:
                    pass
            messagebox.showerror(
                "Export error",
                "The nvram.txt file was not created.\n"
                "The administrator's request may have been denied, or SCEWIN "
                "ended with an error.\n\n"
                + (f"Contents log.txt:\n{extra}" if extra else ""),
            )
            return

        try:
            text, enc = read_text_file(nvram_name)
        except Exception as e:
            messagebox.showerror("Error", f"Unable to read changes:\n{e}")
            return

        self._load_text(text, nvram_name, enc)
        messagebox.showinfo("Success", f"Export completed:\n{nvram_name}")

    def run_scewin_import(self):
        self.save_changes_only()
        if os.name != "nt":
            messagebox.showerror(
                "Недоступно", "Importing via SCEWIN works only on Windows"
            )
            return

        nvram_name = "changes.txt"
        log_name = "log-file.txt"
        self.update_idletasks()

        try:
            subprocess.run(f"SCEWIN_64.exe /I /S changes.txt 2> log.txt", shell=True)
        except subprocess.TimeoutExpired:
            messagebox.showerror(
                "Error", "SCEWIN was not completed within the allotted time."
            )
            return
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start SCEWIN:\n{e}")
            return

        if not os.path.exists(nvram_name):
            extra = ""
            if os.path.exists(log_name):
                try:
                    with open(log_name, "r", errors="replace") as f:
                        extra = f.read().strip()[:800]
                except Exception:
                    pass
            messagebox.showerror(
                "Import error",
                "The changes.txt file was not created.\n"
                "The administrator's request may have been rejected, or SCEWIN"
                "ended with an error.\n\n"
                + (f"Contents log.txt:\n{extra}" if extra else ""),
            )
            return

        try:
            text, enc = read_text_file(nvram_name)
        except Exception as e:
            messagebox.showerror("Error", f"Unable to read the changes:\n{e}")
            return

        messagebox.showinfo("Success", f"The import is complete:\n{nvram_name}")

    def refresh_list(self):
        flt = self.filter_var.get().strip().lower()
        scope = self.search_scope.get()
        if not flt:
            self.filtered = list(self.records)
        elif scope == "name":
            self.filtered = [r for r in self.records if flt in r.name.lower()]
        else:
            self.filtered = [r for r in self.records if flt in r.search_text]
        self.listbox.delete(0, tk.END)
        for r in self.filtered:
            prefix = "* " if r.modified else "  "
            self.listbox.insert(tk.END, prefix + r.name)
        if flt:
            self.match_count_var.set(
                f"Найдено: {len(self.filtered)} из {len(self.records)}"
            )
        else:
            self.match_count_var.set(f"Total: {len(self.records)}")

    def on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        record = self.filtered[sel[0]]
        self.current_record = record
        self.show_record(record)

    def clear_details(self):
        for var in self.info_vars.values():
            var.set("")
        for w in self.options_radio_frame.winfo_children():
            w.destroy()
        self.options_radio_frame.pack_forget()
        self.value_frame.pack_forget()
        self.placeholder_label.pack(anchor=tk.W)
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.config(state=tk.DISABLED)
        self.modified_label.config(text="")

    def show_record(self, record):
        for key, var in self.info_vars.items():
            f = record.get(key)
            var.set(f.value.strip() if f else "")

        # clear edit area
        for w in self.options_radio_frame.winfo_children():
            w.destroy()
        self.option_buttons = []
        self.options_radio_frame.pack_forget()
        self.value_frame.pack_forget()
        for w in self.value_frame.winfo_children():
            w.destroy()
        self.placeholder_label.pack_forget()

        if record.has_options:
            self.options_var.set("")
            for i, opt in enumerate(record.options):
                label = f"[{opt['code']}]  {opt['desc']}"
                rb = ttk.Radiobutton(
                    self.options_radio_frame,
                    text=label,
                    value=str(i),
                    variable=self.options_var,
                )
                rb.pack(anchor=tk.W)
                if opt["marker"]:
                    self.options_var.set(str(i))
            self.options_radio_frame.pack(fill=tk.X, anchor=tk.W)
        else:
            vf = record.value_field
            bd = record.bios_default_field
            row = 0
            if vf is not None:
                m = INNER_RE.match(vf.value)
                inner = m.group(2)[1:-1] if m else vf.value
                self.value_var.set(inner)
                ttk.Label(self.value_frame, text="Value:").grid(
                    row=row, column=0, sticky=tk.W, pady=2
                )
                ttk.Entry(self.value_frame, textvariable=self.value_var, width=20).grid(
                    row=row, column=1, sticky=tk.W, padx=6
                )
                row += 1
            if bd is not None:
                m = INNER_RE.match(bd.value)
                inner = m.group(2)[1:-1] if m else bd.value
                self.bios_default_var.set(inner)
                ttk.Label(self.value_frame, text="BIOS Default:").grid(
                    row=row, column=0, sticky=tk.W, pady=2
                )
                ttk.Label(
                    self.value_frame, textvariable=self.bios_default_var, width=20
                ).grid(row=row, column=1, sticky=tk.W, padx=6)
                row += 1
            if row == 0:
                ttk.Label(
                    self.value_frame, text="No editable fields (Options / Value)."
                ).grid(row=0, column=0, sticky=tk.W)
            self.value_frame.pack(fill=tk.X, anchor=tk.W)

        self.update_preview()
        self.modified_label.config(text="Changed" if record.modified else "")

    def update_preview(self):
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        if self.current_record:
            self.preview_text.insert("1.0", self.current_record.to_text())
        self.preview_text.config(state=tk.DISABLED)

    def apply_change(self):
        record = self.current_record
        if record is None:
            return
        changed = False

        if record.has_options:
            sel = self.options_var.get()
            if sel != "":
                sel_idx = int(sel)
                for i, opt in enumerate(record.options):
                    new_marker = i == sel_idx
                    if opt["marker"] != new_marker:
                        changed = True
                    opt["marker"] = new_marker
        else:
            vf = record.value_field
            if vf is not None:
                m = INNER_RE.match(vf.value)
                if m:
                    new_val = (
                        m.group(1)
                        + m.group(2)[0]
                        + self.value_var.get()
                        + m.group(2)[-1]
                        + m.group(3)
                    )
                else:
                    new_val = self.value_var.get()
                if new_val != vf.value:
                    vf.value = new_val
                    changed = True

            bd = record.bios_default_field
            if bd is not None:
                m = INNER_RE.match(bd.value)
                if m:
                    new_val = (
                        m.group(1)
                        + m.group(2)[0]
                        + self.bios_default_var.get()
                        + m.group(2)[-1]
                        + m.group(3)
                    )
                else:
                    new_val = self.bios_default_var.get()
                if new_val != bd.value:
                    bd.value = new_val
                    changed = True

        if changed:
            record.modified = True
            self.refresh_list()
            # restore selection
            for i, r in enumerate(self.filtered):
                if r is record:
                    self.listbox.selection_set(i)
                    break
            self.update_preview()
            self.modified_label.config(text="Changed")
        else:
            self.modified_label.config(text="No changes")

    # --------------------------------------------------------------- save
    def _compose_text(self, records):
        parts = []
        if self.header_lines and self.include_header_var.get():
            parts.append("\n".join(self.header_lines))
        parts.append("\n\n".join(r.to_text() for r in records) + "\n")
        text = "\n\n".join(parts) if len(parts) > 1 else parts[0]
        if self.newline != "\n":
            text = text.replace("\n", self.newline)
        return text

    def save_changes_only(self):
        changed = [r for r in self.records if r.modified]
        if not changed:
            messagebox.showinfo("Info", "There are no changed settings.")
            return
        text = self._compose_text(changed)
        self._write("changes.txt", text)
        messagebox.showinfo(
            "Success", f"Saved {len(changed)} modified parameters:\nchanges.txt"
        )

    def _suggest_name(self, suffix):
        if self.source_path:
            base = os.path.splitext(os.path.basename(self.source_path))[0]
            return f"{base}{suffix}.txt"
        return f"params{suffix}.txt"

    def _write(self, path, text):
        try:
            with open(path, "w", encoding=self.encoding) as f:
                f.write(text)
        except Exception:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)


if __name__ == "__main__":
    app = App()
    app.mainloop()
