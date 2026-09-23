"""Small local control panel: select project, export requests, import responses."""

import os
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .bridge import Bridge
from .cli import import_return, install, load_config
from .server import BridgeServer


def open_folder(path):
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def launch(project=None):
    window = tk.Tk()
    window.title("Interception — Manual Inference Bridge")
    window.geometry("780x520")
    window.minsize(680, 440)
    state = {"bridge": None, "server": None}
    folder = tk.StringVar(value=project or "Choose the agent project's folder")
    status = tk.StringVar(value="Select a project to begin.")
    frame = ttk.Frame(window, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Interception", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(frame, textvariable=folder, wraplength=720).pack(anchor="w", pady=10)

    def guarded(fn):
        def invoke():
            try:
                fn()
            except Exception as exc:
                messagebox.showerror("Interception", str(exc))

        return invoke

    def select(path=None):
        if state["server"]:
            raise ValueError(
                "Close this window before switching projects; pending requests are saved."
            )
        selected = path or filedialog.askdirectory(title="Choose the agent project")
        if not selected:
            return
        result = install(selected)
        state["bridge"] = Bridge(selected)
        folder.set(str(Path(selected).resolve()))
        status.set("Mailbox ready. Start the bridge, then connect the project's inference client.")
        report.delete("1.0", "end")
        report.insert("end", "Assessment: " + result["recommended_interception"] + "\n\n")
        report.insert("end", "\n".join(result["required_changes"]))

    def bridge():
        if state["bridge"] is None:
            raise ValueError("Choose a project first")
        return state["bridge"]

    def start():
        current = bridge()
        if state["server"]:
            return
        config = load_config(current)
        server = BridgeServer(current, port=config["port"], token=config["token"])
        state["server"] = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        status.set(
            f"Bridge running at 127.0.0.1:{config['port']}. Requests wait until valid answers arrive."
        )

    def export():
        current = bridge()
        current.ingest()
        path = filedialog.asksaveasfilename(
            title="Save batch to upload to ChatGPT",
            initialfile="INFERENCE_BATCH.md",
            defaultextension=".md",
        )
        if path:
            current.export_batch(path)
            status.set(
                "Upload the saved batch to ChatGPT and ask: Fulfill these inference requests."
            )

    def receive():
        current = bridge()
        paths = filedialog.askopenfilenames(
            title="Select downloaded RETURN JSON files", filetypes=[("JSON files", "*.json")]
        )
        for path in paths:
            import_return(current, path)
        if paths:
            status.set(f"Validated {len(paths)} answer(s). Waiting callers can continue.")

    def demo():
        current = bridge()
        current.submit(
            {
                "model": "manual",
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with one short sentence confirming this manual inference test works.",
                    }
                ],
            },
            metadata={"caller": {"agent": "desktop_demo", "step": "hello"}},
        )
        status.set(
            "Test request created. Click Export batch, upload it to ChatGPT, then import the answer."
        )

    for label, fn in [
        ("1. Choose project", select),
        ("2. Start bridge", start),
        ("3. Export batch for ChatGPT", export),
        ("4. Import answers", receive),
        ("Open CATCH / RETURN folders", lambda: open_folder(bridge().home)),
        ("Create test request", demo),
    ]:
        ttk.Button(frame, text=label, command=guarded(fn)).pack(fill="x", pady=3)
    ttk.Label(frame, textvariable=status, wraplength=720).pack(anchor="w", pady=10)
    count = tk.StringVar()
    ttk.Label(frame, textvariable=count).pack(anchor="w")
    report = tk.Text(frame, height=6, wrap="word")
    report.pack(fill="both", expand=True, pady=8)

    def refresh():
        if state["bridge"]:
            rows = state["bridge"].requests()
            pending = sum(row["state"] == "WAITING_FOR_INFERENCE" for row in rows)
            count.set(f"Waiting: {pending}    Completed: {len(rows) - pending}")
        window.after(1000, refresh)

    def close():
        if state["server"]:
            state["server"].shutdown()
            state["server"].server_close()
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    if project:
        guarded(lambda: select(project))()
    refresh()
    window.mainloop()
