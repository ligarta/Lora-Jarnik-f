from storage.system_logger import SystemLogger
from model.file import File
from storage.file_storage import FileStorage
from storage.data_stream_logger import DataStreamLogger
from .crc32_calculator import CRC32Calculator
from .stream_data_generator import StreamDataGenerator
from .stream_data_verifier import StreamDataVerifier
from datetime import datetime
import time
from typing import Callable, Optional
from pathlib import Path
from streaming_engine import StreamingEngine


class Application:
    __slots__ = (
        "logger",
        "file_storage",
        "crc32_calculator",
        "loaded_file",
        "stream_data_generator",
        "stream_data_verifier",
        "data_stream_logger",
        "received_file",
        "streaming_engine",
    )

    logger: SystemLogger
    file_storage: FileStorage
    loaded_file: File | None
    crc32_calculator: CRC32Calculator
    stream_data_generator: StreamDataGenerator
    stream_data_verifier: StreamDataVerifier
    data_stream_logger: DataStreamLogger
    received_file: File | None
    streaming_engine: StreamingEngine

    def __init__(
        self,
        logger: SystemLogger,
        file_storage: FileStorage,
        crc32_calculator: CRC32Calculator,
        stream_data_generator: StreamDataGenerator,
        stream_data_verifier: StreamDataVerifier,
        data_stream_logger: DataStreamLogger,
        streaming_engine: StreamingEngine | None = None,
    ):
        self.logger = logger
        self.loaded_file = None
        self.file_storage = file_storage
        self.crc32_calculator = crc32_calculator
        self.stream_data_generator = stream_data_generator
        self.stream_data_verifier = stream_data_verifier
        self.data_stream_logger = data_stream_logger
        self.received_file = None
        self.streaming_engine = (
            streaming_engine if streaming_engine is not None else StreamingEngine()
        )

    def load_file(self, path: str):
        self.logger.log_event(f"[INFO]: Load file {path}")
        try:
            self.loaded_file = self.file_storage.read_file(path=path)
            self.logger.log_event("[INFO]: File loaded.")
            self.calculate_crc32_of_loaded_file()
        except Exception as e:
            self.logger.log_event(f"[ERROR]: {e}")
            raise e

    def get_loaded_file_path(self) -> str | None:
        if self.loaded_file == None:
            return None
        else:
            return self.loaded_file.path

    def calculate_crc32_of_loaded_file(self) -> str:
        self.logger.log_event("[INFO]: Calculating CRC32 of loaded file")
        if self.loaded_file == None:
            self.logger.log_event("[ERROR]: No file loaded.")
            raise FileNotFoundError(f"File not found.")
        crc_result = self.crc32_calculator.get_crc32(self.loaded_file.data)
        self.logger.log_event(f"[INFO]: CRC32 result {crc_result}")
        return crc_result

    def send_loaded_file(self):
        self.logger.log_event("[INFO]: Start sending file")
        if self.loaded_file == None:
            self.logger.log_event("[ERROR]: No file loaded.")
            raise FileNotFoundError(f"File not found.")
        time.sleep(5)  # replace with send via LoRa
        self.logger.log_event("[INFO]: File sent")

    def start_sending_stream_data(
        self,
        report_sending_data: Callable[[int], None],
        delay: float = 1.0,
        skip_pattern: int | None = None,
    ):
        """
        Kirim data streaming angka 1-100 secara loop melalui LoRa/transport.
        """
        self.logger.log_event("[INFO]: Start sending stream data")
        self.stream_data_generator.reset()
        self.streaming_engine.open(is_receiver=False)
        try:
            while True:
                current_data = self.stream_data_generator.get_data()

                # Jika mode simulasi packet loss aktif, lewati angka tertentu
                if skip_pattern is not None and current_data % skip_pattern == 0:
                    self.logger.log_event(
                        f"[SIMULASI LOSS]: Melewati angka {current_data} (packet loss disengaja)"
                    )
                    time.sleep(delay)
                    continue

                self.logger.log_event(f"[INFO]: Sending stream data: {current_data}")
                self.streaming_engine.send_stream_data(current_data)
                report_sending_data(current_data)
                time.sleep(delay)
        finally:
            self.streaming_engine.close()

    def start_receiving_file(self):
        self.logger.log_event("[INFO]: Start receiving file")
        dummy_file_content = bytes("AWOKWOKWOKWOKWOKWOKWOKWOKWOK", "utf-8")
        time.sleep(5)

        # received_data is full file content. merge chunks must be done before this
        received_data = dummy_file_content

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filepath = Path(f"logs/received_file_{timestamp}.bin")
        filepath_str = str(filepath.resolve())

        self.received_file = File(filepath_str, received_data)
        self.file_storage.save_file(self.received_file)
        self.logger.log_event(f"[INFO]: File received: {filepath_str}")
        self.calculate_crc32_of_received_file()

    def calculate_crc32_of_received_file(self) -> str:
        self.logger.log_event("[INFO]: Calculating CRC32 of received file")
        if self.received_file == None:
            self.logger.log_event("[ERROR]: No received file.")
            raise FileNotFoundError(f"File not found.")
        crc_result = self.crc32_calculator.get_crc32(self.received_file.data)
        self.logger.log_event(f"[INFO]: CRC32 result {crc_result}")
        return crc_result

    def start_receiving_stream_data(
        self,
        report_receiving_data: Callable[..., None],
        report_alarm: Optional[Callable[[str, list[int], Optional[int], Optional[int]], None]] = None,
    ):
        """
        Menerima data stream live dari transport dan memicu alarm jika ada data yang hilang.
        """
        self.logger.log_event("[INFO]: Start receiving stream data")
        self.data_stream_logger.start_session()
        self.stream_data_verifier.reset()
        self.streaming_engine.open(is_receiver=True)

        try:
            while True:
                received_data, err = self.streaming_engine.receive_stream_data(timeout=1.0)
                if received_data is None:
                    if err:
                        self.logger.log_event(f"[ALARM/ERROR]: Paket rusak - {err}")
                        if report_alarm:
                            report_alarm(f"Paket Rusak: {err}", [], None, None)
                    continue

                is_valid, missing, expected = self.stream_data_verifier.check_missing(received_data)

                if not is_valid:
                    self.logger.log_event(
                        f"[ALARM]: Data hilang terdeteksi! Diharapkan: {expected}, Diterima: {received_data}, Hilang: {missing}"
                    )
                    if report_alarm:
                        report_alarm("Data Hilang Terdeteksi", missing, expected, received_data)

                try:
                    report_receiving_data(received_data, is_valid, missing, expected)
                except TypeError:
                    report_receiving_data(received_data, is_valid)

                notes = (
                    f"ALARM_DATA_HILANG: missing {missing} (expected {expected})"
                    if not is_valid and missing
                    else ("OK" if is_valid else "INVALID")
                )
                self.data_stream_logger.log(data=received_data, is_valid=is_valid, notes=notes)

                self.logger.log_event(
                    f"[INFO]: Received stream data: {received_data} {'' if is_valid else '(INVALID)'}"
                )
        finally:
            self.streaming_engine.close()

    def start_receiving_stream_simulation(
        self,
        report_receiving_data: Callable[..., None],
        report_alarm: Optional[Callable[[str, list[int], Optional[int], Optional[int]], None]] = None,
    ):
        """
        Mode simulasi stream receive lokal dengan simulasi packet loss untuk menguji alarm.
        """
        self.logger.log_event("[INFO]: Start receiving stream data (Simulation Mode)")
        self.data_stream_logger.start_session()
        self.stream_data_verifier.reset()
        temp_data = 0

        while True:
            time.sleep(1)
            received_data = temp_data + 1

            # Buat lompatan data (simulasi paket hilang pada kelipatan 5)
            if temp_data > 0 and temp_data % 5 == 0:
                temp_data = temp_data + 2  # melompati data untuk memicu alarm
            else:
                temp_data = (temp_data + 1) % 100

            is_valid, missing, expected = self.stream_data_verifier.check_missing(received_data)

            if not is_valid:
                self.logger.log_event(
                    f"[ALARM]: (Simulasi) Data hilang! Diharapkan: {expected}, Diterima: {received_data}, Hilang: {missing}"
                )
                if report_alarm:
                    report_alarm("Data Hilang (Simulasi)", missing, expected, received_data)

            try:
                report_receiving_data(received_data, is_valid, missing, expected)
            except TypeError:
                report_receiving_data(received_data, is_valid)

            notes = (
                f"ALARM_DATA_HILANG: missing {missing} (expected {expected})"
                if not is_valid and missing
                else ("OK" if is_valid else "INVALID")
            )
            self.data_stream_logger.log(data=received_data, is_valid=is_valid, notes=notes)
            self.logger.log_event(
                f"[INFO]: Received stream data: {received_data} {'' if is_valid else '(INVALID)'}"
            )
