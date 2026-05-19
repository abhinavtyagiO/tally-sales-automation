from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from tkinter import ttk

from connector.main import PollingConnector, settings_from_env


class HelperApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AccountPilot Helper")
        self.root.geometry("380x180")
        self.root.resizable(False, False)
        self.status_var = tk.StringVar(value="Starting AccountPilot Helper...")
        self.last_activity_var = tk.StringVar(value="Last activity: Not yet")
        self.error_var = tk.StringVar(value="")

        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="AccountPilot Helper", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status_var).pack(anchor="w", pady=(14, 4))
        ttk.Label(frame, textvariable=self.last_activity_var).pack(anchor="w")
        ttk.Label(frame, textvariable=self.error_var, foreground="#991b1b", wraplength=330).pack(anchor="w", pady=(10, 0))

        self.connector = PollingConnector(settings_from_env())
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def run(self) -> None:
        self.thread.start()
        self.root.mainloop()

    def _run_loop(self) -> None:
        while True:
            try:
                ran_job = self.connector.run_once()
                if ran_job:
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    HelperApp().run()


if __name__ == "__main__":
    main()
