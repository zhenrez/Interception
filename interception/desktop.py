"""Local control panel for target selection and inference routing."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

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
    window.title("Interception — Inference Router")
    window.geometry("940x780")
    window.minsize(760, 660)

    state = {"bridge": None, "server": None, "worker": None, "assessment": None}
    stop, events = threading.Event(), queue.Queue()

    target = tk.StringVar(
        value="Choose the AI/agent project whose inference calls you want to intercept."
    )
    status = tk.StringVar(value="No target selected.")
    counts = tk.StringVar(value="Waiting inference: 0    Answered inference: 0")
    bridge_state = tk.StringVar(value="Local API bridge: STOPPED")
    relay_state = tk.StringVar(value="GitHub transport: not linked to this target")

    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Interception", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="Intercept model calls → route inference through ChatGPT → return the validated answer.",
        wraplength=880,
    ).pack(anchor="w", pady=(2, 8))
    ttk.Label(frame, textvariable=target, wraplength=880).pack(anchor="w", pady=(0, 8))

    def guarded(fn):
        def invoke():
            try:
                return fn()
            except Exception as exc:
                messagebox.showerror("Interception", str(exc))

        return invoke

    def bridge():
        if state["bridge"] is None:
            raise ValueError("Choose a target project first")
        return state["bridge"]

    def render_assessment(result):
        assessment.delete("1.0", "end")
        assessment.insert("end", f"Target: {result.get('project', 'unknown')}\n")
        assessment.insert(
            "end",
            f"Scanned: {result.get('files_scanned', 0)} files    "
            f"Languages: {', '.join(result.get('source_languages', [])) or 'not detected'}\n",
        )
        assessment.insert(
            "end",
            f"Frameworks: {', '.join(result.get('frameworks', [])) or 'not detected'}\n"
            f"Providers: {', '.join(result.get('providers', [])) or 'not detected'}\n"
            f"Recommended interception: {result.get('recommended_interception', 'unknown')}\n\n",
        )
        surfaces = result.get("inference_surfaces", [])
        if surfaces:
            assessment.insert("end", "Detected inference surfaces:\n")
            for index, surface in enumerate(surfaces, 1):
                assessment.insert(
                    "end",
                    f"  {index}. {surface.get('invocation_protocol', 'UNKNOWN')} "
                    f"→ {surface.get('recommended_interception', 'explicit adapter')} "
                    f"[{surface.get('owner', 'UNKNOWN')}]\n",
                )
        else:
            assessment.insert(
                "end",
                "No supported inference surface was established by static assessment. "
                "This does not prove that the project has no inference calls.\n",
            )
        blockers = result.get("required_changes", [])
        if blockers:
            assessment.insert("end", "\nCurrent boundaries / proof still required:\n")
            for item in blockers:
                assessment.insert("end", f"  • {item}\n")

    def refresh_relay_label():
        current = bridge()
        path = current.home / "github-relay.json"
        if not path.exists():
            relay_state.set("GitHub transport: not linked to this target")
            return
        cfg = loads(path.read_text(encoding="utf-8"))
        request_branch = cfg.get("request_branch", cfg.get("branch", "?"))
        return_branch = cfg.get("return_branch", request_branch)
        relay_state.set(
            f"GitHub transport: {cfg.get('repository', '?')}  "
            f"PR #{cfg.get('pull_request_number', '?')}  "
            f"requests={request_branch}  returns={return_branch}"
        )

    def select(path=None):
        if state["server"] or state["worker"]:
            raise ValueError("Stop the active bridge/test before switching targets.")
        selected = path or filedialog.askdirectory(title="Choose target AI/agent project")
        if not selected:
            return
        result = install(selected)
        state["bridge"] = Bridge(selected)
        state["assessment"] = result
        target.set(str(state["bridge"].root))
        render_assessment(result)
        refresh_relay_label()
        status.set(
            "Target assessed. Start the API bridge or review the detected inference surface."
        )

    ttk.Button(frame, text="Choose target project", command=guarded(select)).pack(fill="x")

    tabs = ttk.Notebook(frame)
    tabs.pack(fill="both", expand=True, pady=10)

    routing = ttk.Frame(tabs, padding=12)
    inference = ttk.Frame(tabs, padding=12)
    diagnostics = ttk.Frame(tabs, padding=12)
    tabs.add(routing, text="Target & routing")
    tabs.add(inference, text="Inference")
    tabs.add(diagnostics, text="Diagnostics")

    ttk.Label(routing, textvariable=bridge_state).pack(anchor="w", pady=(0, 4))
    ttk.Label(routing, textvariable=relay_state, wraplength=850).pack(anchor="w", pady=(0, 10))

    def reassess():
        current = bridge()
        result = install(current.root)
        state["assessment"] = result
        render_assessment(result)
        refresh_relay_label()
        status.set("Target re-assessed.")

    def copy_connection():
        current = bridge()
        path = current.home / "connection.json"
        if not path.exists():
            raise ValueError("Connection settings do not exist yet")
        window.clipboard_clear()
        window.clipboard_append(path.read_text(encoding="utf-8"))
        window.update_idletasks()
        status.set("Copied local API connection settings.")

    ttk.Button(routing, text="Re-assess target", command=guarded(reassess)).pack(fill="x", pady=3)
    ttk.Button(
        routing, text="Copy local API connection settings", command=guarded(copy_connection)
    ).pack(fill="x", pady=3)
    ttk.Button(
        routing,
        text="Open this target's Interception state",
        command=guarded(lambda: open_folder(bridge().home)),
    ).pack(fill="x", pady=3)

    assessment = tk.Text(routing, height=18, wrap="word")
    assessment.pack(fill="both", expand=True, pady=(10, 0))

    def start():
        current = bridge()
        if state["server"]:
            return
        config = load_config(current)
        server = BridgeServer(current, port=config["port"], token=config["token"])
        state["server"] = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        bridge_state.set(f"Local API bridge: RUNNING at 127.0.0.1:{config['port']}")
        status.set("Interception is listening for inference calls from this target.")

    def copy_text(text):
        window.clipboard_clear()
        window.clipboard_append(text)
        window.update_idletasks()

    def export():
        current = bridge()
        current.ingest()
        path = filedialog.asksaveasfilename(
            title="Save pending inference batch",
            initialfile="INFERENCE_BATCH.md",
            defaultextension=".md",
        )
        if path:
            current.export_batch(path)
            status.set("Saved pending inference batch.")

    def copy_batch():
        current = bridge()
        current.ingest()
        copy_text(current.export_batch().read_text(encoding="utf-8"))
        status.set("Copied pending inference requests.")

    def receive():
        current = bridge()
        paths = filedialog.askopenfilenames(
            title="Select RETURN JSON files", filetypes=[("JSON files", "*.json")]
        )
        for path in paths:
            import_return(current, path)
        if paths:
            status.set(f"Validated {len(paths)} RETURN file(s). Waiting callers can continue.")

    def paste_answer():
        current = bridge()
        text = window.clipboard_get().strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if len(text.encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("RETURN exceeds 8 MiB")
        returned = loads(text)
        if not isinstance(returned, dict) or not isinstance(returned.get("request_id"), str):
            raise ValueError("Copy the full RETURN JSON, including request_id")
        rid = returned["request_id"]
        validate_return(current.get(rid)["packet"], returned)
        current.write_return(rid, returned["response"])
        status.set(f"Validated RETURN for {rid}. Waiting caller can continue.")

    ttk.Label(
        inference,
        text="Runtime controls. External agents should call the local OpenAI-compatible endpoint.",
        wraplength=850,
    ).pack(anchor="w", pady=(0, 8))
    ttk.Button(inference, text="Start local API bridge", command=guarded(start)).pack(
        fill="x", pady=3
    )
    ttk.Button(inference, text="Copy pending inference requests", command=guarded(copy_batch)).pack(
        fill="x", pady=3
    )
    ttk.Button(
        inference, text="Paste RETURN JSON from clipboard", command=guarded(paste_answer)
    ).pack(fill="x", pady=3)
    ttk.Button(inference, text="Save pending batch as file", command=guarded(export)).pack(
        fill="x", pady=3
    )
    ttk.Button(inference, text="Import RETURN files", command=guarded(receive)).pack(
        fill="x", pady=3
    )
    ttk.Label(inference, textvariable=counts).pack(anchor="w", pady=10)

    def proof():
        current = bridge()
        if state["worker"]:
            raise ValueError("Diagnostic proof is already waiting for a RETURN.")

        def work():
            try:
                receipt = run_proof(current.root, stop=stop)
                events.put(
                    (
                        "done",
                        f"DIAGNOSTIC PASSED: upstream Prompt Evolver caller resumed with "
                        f"score {receipt['score']}.",
                    )
                )
            except Exception as exc:
                events.put(("error", str(exc)))

        state["worker"] = threading.Thread(target=work, daemon=True)
        state["worker"].start()
        status.set(
            "Diagnostic caller is waiting. Fulfill its inference request, then provide RETURN."
        )

    ttk.Label(
        diagnostics,
        text=(
            "Bundled Prompt Evolver is only a transport diagnostic. It is not part of "
            "Interception's product scope."
        ),
        wraplength=850,
    ).pack(anchor="w", pady=(0, 10))
    ttk.Button(diagnostics, text="Run intercepted-call proof", command=guarded(proof)).pack(
        fill="x", pady=3
    )
    ttk.Button(diagnostics, text="Copy diagnostic request", command=guarded(copy_batch)).pack(
        fill="x", pady=3
    )
    ttk.Button(diagnostics, text="Paste diagnostic RETURN", command=guarded(paste_answer)).pack(
        fill="x", pady=3
    )

    ttk.Label(frame, textvariable=status, wraplength=880).pack(anchor="w", pady=6)

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
                counts.set(
                    f"Waiting inference: {len(pending)}    "
                    f"Answered inference: {len(rows) - len(pending)}"
                )
        except Exception as exc:
            status.set(f"Mailbox status unavailable: {exc}")
        window.after(500, refresh)

    def close():
        if state["worker"] and not messagebox.askyesno(
            "Close waiting diagnostic?",
            "Closing stops this live diagnostic caller. Its durable request remains saved. Close anyway?",
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
