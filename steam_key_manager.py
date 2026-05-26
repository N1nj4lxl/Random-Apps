import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime


class SteamKeyManagerApp:
    THEMES = {
        "True Dark": {
            "bg": "#0d0d0d",
            "panel": "#171717",
            "input_bg": "#1f1f1f",
            "fg": "#f5f5f5",
            "muted": "#b3b3b3",
            "accent": "#4ea3ff",
            "success": "#2ecc71",
            "danger": "#ff5f5f",
        },
        "Dark Pink": {
            "bg": "#140d14",
            "panel": "#231726",
            "input_bg": "#2f1f33",
            "fg": "#ffe8f5",
            "muted": "#d9a9c8",
            "accent": "#ff4fa3",
            "success": "#4de099",
            "danger": "#ff6b8a",
        },
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Steam Code Sorter")
        self.root.geometry("980x640")
        self.root.minsize(900, 580)

        self.style = ttk.Style(self.root)

        self.available_keys: list[str] = []
        self.used_keys: list[str] = []
        self.source_file: Path | None = None

        self.theme_name = tk.StringVar(value="True Dark")
        self.key_count_var = tk.StringVar(value="1")

        self._build_ui()
        self.apply_theme(self.theme_name.get())

    def _build_ui(self):
        self.main = tk.Frame(self.root)
        self.main.pack(fill="both", expand=True, padx=14, pady=14)

        top = tk.Frame(self.main)
        top.pack(fill="x", pady=(0, 10))

        self.file_label = tk.Label(top, text="No key file loaded")
        self.file_label.pack(side="left", padx=(0, 10))

        self.load_btn = tk.Button(top, text="Load Keys (.txt)", command=self.load_keys)
        self.load_btn.pack(side="left")

        tk.Label(top, text="Theme:").pack(side="left", padx=(18, 8))
        self.theme_combo = ttk.Combobox(
            top,
            textvariable=self.theme_name,
            values=list(self.THEMES.keys()),
            state="readonly",
            width=12,
        )
        self.theme_combo.pack(side="left")
        self.theme_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_theme(self.theme_name.get()))

        middle = tk.Frame(self.main)
        middle.pack(fill="x", pady=(2, 12))

        tk.Label(middle, text="How many keys to hand out:").pack(side="left")
        self.key_count_entry = tk.Entry(middle, textvariable=self.key_count_var, width=8)
        self.key_count_entry.pack(side="left", padx=(8, 12))

        self.get_keys_btn = tk.Button(middle, text="Get Next Keys", command=self.get_next_keys)
        self.get_keys_btn.pack(side="left", padx=(0, 10))

        self.mark_used_btn = tk.Button(middle, text="Mark Selected as Used", command=self.mark_selected_as_used)
        self.mark_used_btn.pack(side="left")

        lists_wrap = tk.Frame(self.main)
        lists_wrap.pack(fill="both", expand=True)

        left_panel = tk.Frame(lists_wrap)
        right_panel = tk.Frame(lists_wrap)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right_panel.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self.available_title = tk.Label(left_panel, text="Available Keys (not yet used)")
        self.available_title.pack(anchor="w", pady=(0, 6))

        self.available_list = tk.Listbox(left_panel, selectmode="extended")
        self.available_list.pack(fill="both", expand=True)

        self.used_title = tk.Label(right_panel, text="Used Keys")
        self.used_title.pack(anchor="w", pady=(0, 6))

        self.used_list = tk.Listbox(right_panel)
        self.used_list.pack(fill="both", expand=True)

        bottom = tk.Frame(self.main)
        bottom.pack(fill="x", pady=(10, 0))

        self.save_btn = tk.Button(bottom, text="Save Current State", command=self.save_state)
        self.save_btn.pack(side="left")

        self.stats_label = tk.Label(bottom, text="Available: 0 | Used: 0")
        self.stats_label.pack(side="right")

    def apply_theme(self, theme_name: str):
        c = self.THEMES[theme_name]
        self.root.configure(bg=c["bg"])
        for widget in [self.main, *self.main.winfo_children()]:
            widget.configure(bg=c["bg"])

        for panel in self.main.winfo_children():
            for child in panel.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=c["panel"])
                    for grand in child.winfo_children():
                        if isinstance(grand, tk.Label):
                            grand.configure(bg=c["panel"], fg=c["fg"])
                elif isinstance(child, tk.Label):
                    child.configure(bg=panel.cget("bg"), fg=c["fg"])

        base_btn_conf = {
            "bg": c["accent"],
            "fg": "white",
            "activebackground": c["danger"],
            "activeforeground": "white",
            "relief": "flat",
            "bd": 0,
            "padx": 10,
            "pady": 6,
        }

        for btn in [self.load_btn, self.get_keys_btn, self.mark_used_btn, self.save_btn]:
            btn.configure(**base_btn_conf)

        self.key_count_entry.configure(
            bg=c["input_bg"],
            fg=c["fg"],
            insertbackground=c["fg"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=c["accent"],
            highlightcolor=c["accent"],
        )

        for listbox in [self.available_list, self.used_list]:
            listbox.configure(
                bg=c["input_bg"],
                fg=c["fg"],
                selectbackground=c["accent"],
                selectforeground="white",
                relief="flat",
                highlightthickness=1,
                highlightbackground=c["accent"],
            )

        self.style.theme_use("clam")
        self.style.configure(
            "TCombobox",
            fieldbackground=c["input_bg"],
            background=c["input_bg"],
            foreground=c["fg"],
            arrowcolor=c["fg"],
        )

        self.file_label.configure(fg=c["muted"])
        self.stats_label.configure(fg=c["success"])

    def update_stats(self):
        self.stats_label.config(text=f"Available: {len(self.available_keys)} | Used: {len(self.used_keys)}")

    def load_keys(self):
        file_path = filedialog.askopenfilename(
            title="Select Steam key text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            messagebox.showerror("File Error", f"Could not read file:\n{exc}")
            return

        keys = [line.strip() for line in lines if line.strip()]
        deduped = list(dict.fromkeys(keys))

        if not deduped:
            messagebox.showwarning("No Keys", "This file does not contain any non-empty keys.")
            return

        self.available_keys = deduped
        self.used_keys = []
        self.source_file = path
        self.file_label.config(text=f"Loaded: {path.name} ({len(deduped)} keys)")
        self.refresh_lists()

    def refresh_lists(self):
        self.available_list.delete(0, tk.END)
        self.used_list.delete(0, tk.END)

        for key in self.available_keys:
            self.available_list.insert(tk.END, key)

        for key in self.used_keys:
            self.used_list.insert(tk.END, key)

        self.update_stats()

    def _parse_requested_count(self) -> int | None:
        raw = self.key_count_var.get().strip()
        if not raw.isdigit() or int(raw) <= 0:
            messagebox.showwarning("Invalid Number", "Please enter a positive whole number.")
            return None
        return int(raw)

    def get_next_keys(self):
        count = self._parse_requested_count()
        if count is None:
            return

        if not self.available_keys:
            messagebox.showinfo("No Keys Left", "There are no available keys left to hand out.")
            return

        count = min(count, len(self.available_keys))
        self.available_list.selection_clear(0, tk.END)
        for i in range(count):
            self.available_list.selection_set(i)

        selected_keys = self.available_keys[:count]
        messagebox.showinfo("Keys Ready", "\n".join(selected_keys))

    def mark_selected_as_used(self):
        indexes = list(self.available_list.curselection())
        if not indexes:
            messagebox.showwarning("Nothing Selected", "Select one or more keys to mark as used.")
            return

        moved = [self.available_keys[i] for i in indexes]
        for i in sorted(indexes, reverse=True):
            del self.available_keys[i]

        self.used_keys.extend(moved)
        self.refresh_lists()

    def save_state(self):
        if self.source_file is None:
            messagebox.showwarning("No Source File", "Load a key file before saving state.")
            return

        base = self.source_file.stem
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        available_out = self.source_file.with_name(f"{base}_available_{stamp}.txt")
        used_out = self.source_file.with_name(f"{base}_used_{stamp}.txt")

        try:
            available_out.write_text("\n".join(self.available_keys), encoding="utf-8")
            used_out.write_text("\n".join(self.used_keys), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Save Error", f"Could not save state:\n{exc}")
            return

        messagebox.showinfo(
            "Saved",
            f"Saved current state:\n- {available_out.name}\n- {used_out.name}",
        )


if __name__ == "__main__":
    root = tk.Tk()
    app = SteamKeyManagerApp(root)
    root.mainloop()
