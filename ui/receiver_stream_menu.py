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
            print("1. Listen Stream (Live via Transport / LoRa)")
            print("2. Test Stream & Alarm (Mode Simulasi Lokal)")
            print("0. Back")
            print()

            choice = input("Your choice: ").strip()
            if choice == "1":
                self._show_receiving_data()
            elif choice == "2":
                self._show_simulation_data()
            elif choice == "0":
                self.want_to_move = True
                self.set_next_screen_fn(UIMenu.RECEIVER)
            else:
                print()
                print("!!! INVALID SELECTION !!!")
                print()

    def _trigger_alarm(
        self,
        reason: str,
        missing: list[int],
        expected: int | None,
        received: int | None,
    ):
        """
        Memicu alarm suara dan alarm visual jika terdeteksi data hilang.
        """
        # Alarm Suara (Beep)
        try:
            import winsound
            winsound.Beep(1200, 150)
            winsound.Beep(1600, 250)
        except Exception:
            pass
        print("\a", end="", flush=True)

        # Alarm Visual di Layar
        print()
        print("!" * 64)
        print(f"🚨 [ALARM: {reason.upper()}!] 🚨")
        if expected is not None:
            print(f"   Diharapkan Data : {expected}")
        if received is not None:
            print(f"   Diterima Data   : {received}")
        if missing:
            print(f"   Data Yang Hilang: {missing} (Total: {len(missing)} data)")
        print("!" * 64)
        print()

    def _print_received_data(
        self,
        data: int,
        is_valid: bool,
        missing: list[int] | None = None,
        expected: int | None = None,
    ):
        if is_valid:
            print(f"Received stream: {data} [OK]")
        else:
            loss_detail = f" -> HILANG: {missing}" if missing else ""
            print(f"Received stream: {data} [INVALID / ALARM]{loss_detail}")

    def _show_receiving_data(self):
        print()
        print("Press Ctrl+C to stop. Menunggu & mendengarkan stream data...")
        print()
        try:
            self.application.start_receiving_stream_data(
                report_receiving_data=self._print_received_data,
                report_alarm=self._trigger_alarm,
            )
        except KeyboardInterrupt:
            print()
            print("[INFO]: Stream listening dihentikan oleh user (Ctrl+C).")
            self._print_summary()

    def _show_simulation_data(self):
        print()
        print(">>> MODE SIMULASI STREAM AKTIF: Menguji verifikasi & alarm data hilang <<<")
        print("Press Ctrl+C to stop.")
        print()
        try:
            self.application.start_receiving_stream_simulation(
                report_receiving_data=self._print_received_data,
                report_alarm=self._trigger_alarm,
            )
        except KeyboardInterrupt:
            print()
            print("[INFO]: Simulasi dihentikan oleh user (Ctrl+C).")
            self._print_summary()

    def _print_summary(self):
        v = self.application.stream_data_verifier
        print()
        print("=" * 40)
        print("   RINGKASAN STATISTIK STREAMING")
        print("=" * 40)
        print(f" Total Paket Diterima : {v.total_received}")
        print(f" Paket Valid Berurutan: {v.valid_count}")
        print(f" Data Hilang (Lost)   : {v.lost_count}")
        print(f" Total Alarm Dipicu   : {v.alarm_count}")
        total_packets = v.valid_count + v.lost_count
        if total_packets > 0:
            loss_rate = (v.lost_count / total_packets) * 100
            print(f" Tingkat Kehilangan   : {loss_rate:.2f}%")
        print("=" * 40)
        print()
        input("Press Enter to continue...")
