"""Project-scoped goal handoff and inference control panel."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import brief
from .bridge import Bridge
from .cli import import_return, install, load_config
from .contracts import validate_return
from .files import loads
from .proof import run as run_proof
from .server import BridgeServer


def open_folder(path):
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def launch(project=None):
    window = tk.Tk()
    window.title("Interception — one project at a time")
    window.geometry("900x820")
    window.minsize(720, 700)
    state = {"bridge": None, "server": None, "revision": 0, "worker": None}
    stop, events = threading.Event(), queue.Queue()
    folder = tk.StringVar(value="Choose the project you want to work on")
    status = tk.StringVar(value="Your goal and inference mailbox stay in the selected project.")
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Interception", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(frame, textvariable=folder, wraplength=840).pack(anchor="w", pady=6)

    def guarded(fn):
        def invoke():
            try:
                return fn()
            except Exception as exc:
                messagebox.showerror("Interception", str(exc))

        return invoke

    def bridge():
        if state["bridge"] is None:
            raise ValueError("Choose a project first")
        return state["bridge"]

    def select(path=None):
        if state["server"] or state["worker"]:
            raise ValueError("Open another window for another project, or close this one first.")
        selected = path or filedialog.askdirectory(title="Choose this project's folder")
        if not selected:
            return
        result = install(selected)
        state["bridge"] = Bridge(selected)
        folder.set(str(state["bridge"].root))
        saved = brief.load(state["bridge"]) or {}
        state["revision"] = saved.get("revision", 0)
        for name, field in fields.items():
            field.delete("1.0", "end")
            field.insert("1.0", saved.get(name, ""))
        status.set("Project ready. Describe the goal, or open Inference to test the connection.")
        report.delete("1.0", "end")
        report.insert("end", "Assessment: " + result["recommended_interception"] + "\n")
        report.insert("end", "\n".join(result["required_changes"]))

    ttk.Button(frame, text="Choose project folder", command=guarded(select)).pack(fill="x")
    tabs = ttk.Notebook(frame)
    tabs.pack(fill="both", expand=True, pady=10)
    goals, inference = ttk.Frame(tabs, padding=12), ttk.Frame(tabs, padding=12)
    tabs.add(goals, text="Goal and procedure")
    tabs.add(inference, text="Inference")
    ttk.Label(
        goals,
        text="Use your own words. The chat handoff includes the working procedure.",
        wraplength=800,
    ).pack(anchor="w", pady=4)
    fields = {}
    for name, label, height in [
        ("goal", "What do you want finished or improved?", 3),
        ("guidelines", "Guidelines — how you want the work approached", 2),
        ("constraints", "Constraints — limits and things that must not change", 2),
        ("done_when", "Done means… (optional; the assistant will help establish this)", 2),
    ]:
        ttk.Label(goals, text=label).pack(anchor="w", pady=(8, 2))
        field = tk.Text(goals, height=height, wrap="word", undo=True)
        field.pack(fill="x")
        fields[name] = field

    def save_goal():
        body = brief.save(
            bridge(),
            expected_revision=state["revision"],
            **{name: field.get("1.0", "end-1c") for name, field in fields.items()},
        )
        state["revision"] = body["revision"]
        status.set(f"Goal saved as revision {body['revision']}. No project execution started.")

    def copy_text(text):
        window.clipboard_clear()
        window.clipboard_append(text)
        window.update_idletasks()

    def copy_handoff():
        save_goal()
        copy_text(brief.handoff(bridge()))
        status.set(
            "Paste into the project's chat with its repository connected. Keep this window open."
        )

    ttk.Button(goals, text="Save goal", command=guarded(save_goal)).pack(fill="x", pady=(12, 3))
    ttk.Button(
        goals, text="Copy goal + working procedure for chat", command=guarded(copy_handoff)
    ).pack(fill="x", pady=3)
    ttk.Label(
        goals,
        text="Chat performs authorized project work. This panel preserves your brief "
        "and transports inference; it does not itself execute arbitrary projects.",
        wraplength=800,
    ).pack(anchor="w", pady=8)

    def start():
        current = bridge()
        if state["server"]:
            return
        config = load_config(current)
        server = BridgeServer(current, port=config["port"], token=config["token"])
        state["server"] = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        status.set(f"API bridge running at 127.0.0.1:{config['port']}.")

    def export():
        current = bridge()
        current.ingest()
        path = filedialog.asksaveasfilename(
            title="Save requests for ChatGPT",
            initialfile="INFERENCE_BATCH.md",
            defaultextension=".md",
        )
        if path:
            current.export_batch(path)
            status.set("Upload the batch to ChatGPT: Fulfill these inference requests.")

    def copy_batch():
        current = bridge()
        current.ingest()
        copy_text(current.export_batch().read_text(encoding="utf-8"))
        status.set("Paste into ChatGPT. Ask it to return the complete RETURN JSON envelope.")

    def receive():
        current = bridge()
        paths = filedialog.askopenfilenames(
            title="Select RETURN JSON files", filetypes=[("JSON files", "*.json")]
        )
        for path in paths:
            import_return(current, path)
        if paths:
            status.set(f"Validated {len(paths)} answer(s). Waiting callers can continue.")

    def paste_answer():
        current = bridge()
        text = window.clipboard_get().strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if len(text.encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("RETURN exceeds 8 MiB")
        returned = loads(text)
        if not isinstance(returned, dict) or not isinstance(returned.get("request_id"), str):
            raise ValueError("Copy the full RETURN JSON, including its request_id")
        rid = returned["request_id"]
        validate_return(current.get(rid)["packet"], returned)
        current.write_return(rid, returned["response"])
        status.set(f"Validated answer for {rid}. Waiting caller can continue.")

    def proof():
        current = bridge()
        if state["worker"]:
            raise ValueError("The bundled test is already waiting; fulfill its request first.")

        def work():
            try:
                receipt = run_proof(current.root, stop=stop)
                events.put(
                    (
                        "done",
                        f"RESUMED: Prompt Evolver returned {receipt['score']}. "
                        "Local inference proof saved; project completion is separate.",
                    )
                )
            except Exception as exc:
                events.put(("error", str(exc)))

        state["worker"] = threading.Thread(target=work, daemon=True)
        state["worker"].start()
        status.set(
            "Prompt Evolver is waiting. Copy its request to chat, then paste the RETURN JSON."
        )

    ttk.Label(
        inference,
        text="First proof: run test → copy request to chat → paste RETURN → caller resumes.",
        wraplength=800,
    ).pack(anchor="w", pady=8)
    for label, fn in [
        ("1. Run bundled Prompt Evolver test", proof),
        ("2. Copy waiting requests for ChatGPT", copy_batch),
        ("3. Paste RETURN JSON from clipboard", paste_answer),
        ("Save request batch as a file", export),
        ("Import RETURN files", receive),
        ("Start API bridge (for connected external agents)", start),
        ("Open this project's CATCH / RETURN folders", lambda: open_folder(bridge().home)),
    ]:
        ttk.Button(inference, text=label, command=guarded(fn)).pack(fill="x", pady=3)
    count = tk.StringVar()
    ttk.Label(inference, textvariable=count).pack(anchor="w", pady=8)
    report = tk.Text(inference, height=8, wrap="word")
    report.pack(fill="both", expand=True)
    ttk.Label(frame, textvariable=status, wraplength=840).pack(anchor="w", pady=6)

    def refresh():
        try:
            while True:
                kind, message = events.get_nowait()
                state["worker"] = None
                status.set(message)
                if kind == "error":
                    messagebox.showerror("Interception", message)
        except queue.Empty:
            pass
        try:
            if state["bridge"]:
                rows = state["bridge"].requests()
                pending = [row for row in rows if row["state"] == "WAITING_FOR_INFERENCE"]
                count.set(
                    f"Waiting inference: {len(pending)}    Answered inference: {len(rows) - len(pending)}"
                )
        except Exception as exc:
            status.set(f"Mailbox status unavailable: {exc}")
        window.after(500, refresh)

    def close():
        if state["worker"] and not messagebox.askyesno(
            "Close waiting test?",
            "Closing stops the live test caller. Its request stays saved, "
            "but this caller cannot resume after closing. Close anyway?",
        ):
            return
        stop.set()
        if state["server"]:
            state["server"].shutdown()
            state["server"].server_close()
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    if project:
        guarded(lambda: select(project))()
    refresh()
    window.mainloop()
