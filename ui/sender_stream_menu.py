from typing import Callable
from .ui_menu import UIMenu
from app.application import Application
import time


class SenderStreamMenu:
    __slots__ = ("want_to_move", "set_next_screen_fn", "application")

    want_to_move: bool
    set_next_screen_fn: Callable[[UIMenu], None]
    application: Application

    def __init__(
        self, set_next_screen_fn: Callable[[UIMenu], None], application: Application
    ):
        self.want_to_move = False
        self.set_next_screen_fn = set_next_screen_fn
        self.application = application

    def show(self):
        self.want_to_move = False
        while not self.want_to_move:
            print()
            print("=== SENDER STREAM MENU ===")
            print()
            print("What should system do?")
            print("1. Send Stream (Normal Loop 1-100)")
            print("2. Send Stream (Simulasi Packet Loss untuk Test Alarm)")
            print("0. Back")
            print()

            choice = input("Your choice: ").strip()
            if choice == "1":
                self._show_stream_progress(skip_loss=False)
            elif choice == "2":
                self._show_stream_progress(skip_loss=True)
            elif choice == "0":
                self.want_to_move = True
                self.set_next_screen_fn(UIMenu.SENDER)
            else:
                print()
                print("!!! INVALID SELECTION !!!")
                print()

    def _show_stream_progress(self, skip_loss: bool = False):
        print()
        if skip_loss:
            print(">>> MODE SIMULASI LOSS DIAKTIFKAN: Angka kelipatan 7 sengaja dilewati untuk memicu alarm di receiver! <<<")
        print("Press Ctrl+C to stop. Stream will start in 2 seconds...")
        time.sleep(2)
        print()
        try:
            self.application.start_sending_stream_data(
                report_sending_data=self._print_sending_data,
                skip_pattern=7 if skip_loss else None,
            )
        except KeyboardInterrupt:
            print()
            print("[INFO]: Streaming dihentikan oleh user (Ctrl+C).")
            print()
            input("Press Enter to continue...")

    def _print_sending_data(self, current_data: int):
        print(f"Sending stream data: {current_data}")
