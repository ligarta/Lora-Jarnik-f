from typing import Callable
from .ui_menu import UIMenu
from app.application import Application


class ReceiverStreamMenu:
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
            print("=== RECEIVER STREAM MENU ===")
            print()
            print("What should system do?")
            print("1. Listen Stream")
            print("0. Back")
            print()

            choice = input("Your choice: ").strip()
            if choice == "1":
                self._show_receiving_data()
            elif choice == "0":
                self.want_to_move = True
                self.set_next_screen_fn(UIMenu.RECEIVER)
            else:
                print()
                print("!!! INVALID SELECTION !!!")
                print()

    def _show_receiving_data(self):
        print()
        print("Press Ctrl+C to stop. Listening data...")
        print()
        self.application.start_receiving_stream_data(
            report_receiving_data=self._print_received_data
        )

    def _print_received_data(self, data: int, is_valid: bool):
        status = " (INVALID)" if not is_valid else ""
        print(f"Received: {data}{status}")
