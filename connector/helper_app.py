from __future__ import annotations

import logging
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

from connector.main import PollingConnector, build_parser, configure_from_setup_args, configure_logging, settings_from_env


class HelperApp:
    def __init__(self, startup_error: str = "") -> None:
        self.root = tk.Tk()
        self.root.title("AccountPilot Helper")
        self.root.geometry("380x180")
        self.root.resizable(False, False)
        self.status_var = tk.StringVar(value="Starting AccountPilot Helper...")
        self.last_activity_var = tk.StringVar(value="Last activity: Not yet")
        self.error_var = tk.StringVar(value=startup_error)

        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="AccountPilot Helper", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status_var).pack(anchor="w", pady=(14, 4))
        ttk.Label(frame, textvariable=self.last_activity_var).pack(anchor="w")
        ttk.Label(frame, textvariable=self.error_var, foreground="#991b1b", wraplength=330).pack(anchor="w", pady=(10, 0))

        self.connector = None
        if not startup_error:
            try:
                self.connector = PollingConnector(settings_from_env())
            except Exception as exc:
                startup_error = f"Setup is incomplete: {exc}"
                self.error_var.set(startup_error)
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def run(self) -> None:
        if self.connector:
            self.thread.start()
        else:
            self.status_var.set("Connection needs attention")
        self.root.mainloop()

    def _run_loop(self) -> None:
        while True:
            try:
                if not self.connector:
                    return
                job_count = self.connector.run_until_idle()
                if job_count:
                    self._set_status("AccountPilot connected", "")
                    self.root.after(0, self.last_activity_var.set, f"Last activity: {time.strftime('%I:%M %p')}")
                else:
                    self._set_status("AccountPilot connected. Waiting for Tally work.", "")
                time.sleep(self.connector.settings.poll_interval_seconds)
            except Exception as exc:
                self._set_status("Connection needs attention", str(exc))
                time.sleep(min(self.connector.settings.max_backoff_seconds, 10))

    def _set_status(self, status: str, error: str) -> None:
        self.root.after(0, self.status_var.set, status)
        self.root.after(0, self.error_var.set, error)


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:])
    startup_error = ""
    try:
        configure_from_setup_args(args)
    except Exception as exc:
        startup_error = f"Setup failed: {exc}"
    if args.configure_only:
        if startup_error:
            raise RuntimeError(startup_error)
        return
    HelperApp(startup_error).run()


if __name__ == "__main__":
    main()
