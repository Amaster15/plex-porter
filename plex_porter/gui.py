"""Three main actions, with custom paths hidden under Advanced."""
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from . import core, platforms, installer, controls, __version__
from . import diagnostics, rollback

BG, PANEL, TEXT, MUTED, GOLD = "#101923", "#192633", "#edf3f7", "#adc0ce", "#e5b657"


class App:
    def __init__(self, root):
        self.root, self.busy = root, False
        self.session_log = diagnostics.SessionLog()
        self.events = queue.Queue(maxsize=256)
        self.buttons = []
        root.title(f"Plex Porter {__version__}")
        root.geometry("820x690")
        root.minsize(760, 650)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("TButton", background=PANEL, foreground=TEXT, padding=(14, 10))
        style.map("TButton", background=[("active", "#304457")], foreground=[("disabled", "#70808b")])
        style.configure("Main.TButton", background=GOLD, foreground=BG, padding=(18, 18), font=("Segoe UI", 15, "bold"))
        style.map("Main.TButton", background=[("active", "#f5ca78"), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
        style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT, padding=6)
        wrap = ttk.Frame(root, padding=26)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="PLEX PORTER", foreground=GOLD, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(wrap, text="Your library. A new home.", font=("Segoe UI", 27, "bold")).pack(anchor="w", pady=(7, 4))
        ttk.Label(wrap, text="Windows ↔ Linux  •  Database, artwork and watched history", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(wrap, text="Your movies, TV shows and music are never backed up.", foreground=GOLD).pack(anchor="w", pady=(18, 4))
        ttk.Label(wrap, text="Close Plex before exporting or importing. Your existing data is kept on import.", style="Muted.TLabel").pack(anchor="w", pady=(0, 20))
        row = ttk.Frame(wrap)
        row.pack(fill="x")
        for col, (title, command) in enumerate((("Export", self.export), ("Import", self.restore))):
            row.columnconfigure(col, weight=1)
            button = ttk.Button(row, text=title, style="Main.TButton", command=command)
            button.grid(row=0, column=col, sticky="ew", padx=(0, 10) if col == 0 else (0, 0))
            self.buttons.append(button)
        row = ttk.Frame(wrap)
        row.pack(fill="x", pady=(10, 18))
        system = "Windows" if platforms.host_os() == "windows" else "Linux"
        for text, command in ((f"Install Plex for {system}", self.install), ("Verify a backup", self.verify)):
            button = ttk.Button(row, text=text, command=command)
            button.pack(side="left", padx=(0, 10))
            self.buttons.append(button)
        ttk.Button(row, text="Advanced ▾", command=self.toggle_advanced).pack(side="right")
        controls_row = ttk.Frame(wrap)
        controls_row.pack(fill="x", pady=(0, 14))
        for text, command in (("Open Plex", self.open_plex), ("Shut Down Plex", self.shutdown_plex),
                              ("Roll Back", self.roll_back), ("Save Support Report", self.save_report)):
            button = ttk.Button(controls_row, text=text, command=command)
            button.pack(side="left", padx=(0, 10))
            self.buttons.append(button)
        self.advanced = ttk.Frame(wrap)
        self.data = tk.StringVar(value=str(platforms.default_data()))
        self.owner = tk.StringVar(value="plex:plex")
        ttk.Label(self.advanced, text="Custom Plex data folder (used for export and import)").pack(anchor="w")
        row = ttk.Frame(self.advanced)
        row.pack(fill="x", pady=(3, 6))
        ttk.Entry(row, textvariable=self.data).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=self.browse).pack(side="left", padx=(8, 0))
        if platforms.host_os() == "linux":
            ttk.Label(self.advanced, text="Linux service owner (user:group)").pack(anchor="w")
            ttk.Entry(self.advanced, textvariable=self.owner).pack(fill="x", pady=(3, 8))
        self.status = tk.StringVar(value="Ready. Export a ZIP here, then import it on your new computer.")
        self.status_label = ttk.Label(wrap, textvariable=self.status, wraplength=750, style="Muted.TLabel")
        self.status_label.pack(anchor="w", pady=(4, 8))
        self.bar = ttk.Progressbar(wrap, mode="indeterminate")
        self.bar.pack(fill="x")
        self.log = tk.Text(wrap, height=8, bg=PANEL, fg=TEXT, relief="flat", font=("Consolas", 9), wrap="word", padx=12, pady=10)
        self.log.pack(fill="both", expand=True, pady=(10, 0))
        self.log.configure(state="disabled")
        self.root.after(100, self.poll)

    def toggle_advanced(self):
        if self.advanced.winfo_manager():
            self.advanced.pack_forget()
        else:
            self.advanced.pack(fill="x", before=self.status_label)

    def browse(self):
        if not self.busy:
            path = filedialog.askdirectory(title="Plex data folder")
            if path:
                self.data.set(path)

    def progress(self, message):
        message = diagnostics.redact(message)
        self.session_log.write(message)
        try:
            self.events.put_nowait(("progress", message))
        except queue.Full:
            pass

    def run(self, job):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")
        self.bar.start()
        self.status.set("Working…")
        self.session_log.write('Operation started')
        def worker():
            try:
                result = diagnostics.redact(job())
                self.session_log.write(result)
                self.events.put(("done", result))
            except Exception as error:
                self.session_log.write(traceback.format_exc(), error=True)
                self.events.put(("error", diagnostics.redact(str(error)) + '\nUse Save Support Report to save the error details.'))
        threading.Thread(target=worker, daemon=False).start()

    def run_migration(self, action, job):
        if self.busy:
            return
        close_first = False
        try:
            platforms.ensure_stopped()
        except platforms.PlexRunningError:
            close_first = messagebox.askyesno(
                "Plex is still running",
                f"Plex must be stopped before {action.lower()}.\n\n"
                "Shut down Plex and continue automatically? Current streams will disconnect.\n\n"
                "Choose No to cancel without changing anything.", parent=self.root)
            if not close_first:
                self.status.set(f"{action} cancelled. Plex was left running.")
                return
        except Exception as error:
            if hasattr(self, 'session_log'):
                self.session_log.write(traceback.format_exc(), error=True)
            messagebox.showerror("Cannot check Plex", str(error), parent=self.root)
            return

        def guarded_job():
            if close_first:
                self.progress(controls.shutdown_plex(self.progress))
            # Check again after shutdown, or if Plex started while a dialog was open.
            platforms.ensure_stopped()
            return job()
        self.run(guarded_job)

    def export(self):
        if self.busy:
            return
        output = filedialog.asksaveasfilename(title="Save Plex backup", initialfile=f"Plex-Library-{datetime.now():%Y-%m-%d}.zip", defaultextension=".zip", filetypes=[("Plex backup", "*.zip")])
        if not output:
            return
        data = self.data.get()
        def job():
            result = core.export_backup(data, output, self.progress)
            return f"Backup saved: {output}\n{len(result['files'])} library files included. No movies or music."
        self.run_migration("Export", job)

    def verify(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title="Verify Plex backup", filetypes=[("Plex backup", "*.zip")])
        if path:
            def job():
                result = core.inspect_backup(path, progress=self.progress)
                return f"Verified all {len(result['files'])} files. Backup is intact."
            self.run(job)

    def restore(self):
        if self.busy:
            return
        archive = filedialog.askopenfilename(title="Import Plex backup", filetypes=[("Plex backup", "*.zip")])
        if not archive:
            return
        target, owner = self.data.get(), self.owner.get()
        if not messagebox.askyesno("Import library", f"Restore to:\n{target}\n\nYour existing Plex data will be kept as a rollback copy. Movies and music will not be touched.\n\nPlex must be closed. Import now?"):
            return
        def job():
            report = core.restore_backup(archive, target, owner, self.progress)
            return "Import complete.\n" + json.dumps(report, indent=2)
        self.run_migration("Import", job)

    def install(self):
        if self.busy:
            return
        if messagebox.askyesno("Install Plex Media Server", "Download the official Plex Media Server installer and run it?\n\nInternet access and administrator approval may be required. If Plex is already installed, this may update it."):
            self.run(lambda: installer.install_plex(self.progress))

    def roll_back(self):
        if self.busy:
            return
        target = self.data.get()
        saved = filedialog.askdirectory(title='Select a Plex Media Server.before- rollback folder',
                                        initialdir=str(Path(target).parent))
        if not saved:
            return
        try:
            rollback.validate(target, saved)
        except Exception as error:
            self.session_log.write(traceback.format_exc(), error=True)
            messagebox.showerror('Cannot roll back', diagnostics.redact(error), parent=self.root)
            return
        if not messagebox.askyesno('Restore previous installation',
                f'Restore this saved installation:\n{saved}\n\nTo:\n{target}\n\n'
                'Library changes and watched history since that copy will be replaced. '
                'Your current installation will be kept as another rollback copy. '
                'Media files will not be changed. Plex will remain stopped afterward.\n\nContinue?', parent=self.root):
            return
        self.run_migration('Rollback', lambda: rollback.restore(target, saved, self.progress))

    def save_report(self):
        if self.busy:
            return
        path = filedialog.asksaveasfilename(title='Save support report',
                initialfile=f'Plex-Porter-Support-{datetime.now():%Y-%m-%d}.txt',
                defaultextension='.txt', filetypes=[('Text report', '*.txt')])
        if path:
            try:
                self.session_log.save(path)
                messagebox.showinfo('Support report saved',
                    f'Saved to:\n{path}\n\nReview paths and filenames before sharing. '
                    'Known token and password fields are redacted. Plex logs and preferences are not included.', parent=self.root)
            except Exception as error:
                messagebox.showerror('Cannot save report', diagnostics.redact(error), parent=self.root)

    def open_plex(self):
        if not self.busy:
            self.run(controls.open_plex)

    def shutdown_plex(self):
        if not self.busy:
            self.run(lambda: controls.shutdown_plex(self.progress))

    def poll(self):
        for _ in range(50):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            self.status.set(value.splitlines()[0])
            self.log.configure(state="normal")
            self.log.insert("end", value + "\n")
            if int(self.log.index("end-1c").split(".")[0]) > 300:
                self.log.delete("1.0", "100.0")
            self.log.see("end")
            self.log.configure(state="disabled")
            if kind in ("done", "error"):
                self.busy = False
                self.bar.stop()
                for button in self.buttons:
                    button.configure(state="normal")
                if kind == "error":
                    messagebox.showerror("Could not complete operation", value)
                else:
                    messagebox.showinfo("Finished", value)
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo("Operation in progress", "Wait for the current operation to finish before closing.")
        else:
            self.session_log.close()
            self.root.destroy()


def launch():
    root = tk.Tk()
    App(root)
    root.mainloop()
