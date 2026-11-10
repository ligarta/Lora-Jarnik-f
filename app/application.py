from storage.system_logger import SystemLogger
from model.file import File
from storage.file_storage import FileStorage
from storage.data_stream_logger import DataStreamLogger
from .crc32_calculator import CRC32Calculator
from .stream_data_generator import StreamDataGenerator
from .stream_data_verifier import StreamDataVerifier
from datetime import datetime
import time
from typing import Callable
from pathlib import Path


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
        "transport",
    )

    logger: SystemLogger
    file_storage: FileStorage
    loaded_file: File | None
    crc32_calculator: CRC32Calculator
    stream_data_generator: StreamDataGenerator
    stream_data_verifier: StreamDataVerifier
    data_stream_logger: DataStreamLogger
    received_file: File | None

    def __init__(
        self,
        logger: SystemLogger,
        file_storage: FileStorage,
        crc32_calculator: CRC32Calculator,
        stream_data_generator: StreamDataGenerator,
        stream_data_verifier: StreamDataVerifier,
        data_stream_logger: DataStreamLogger,
        transport=None,
    ):
        self.logger = logger
        self.loaded_file = None
        self.file_storage = file_storage
        self.crc32_calculator = crc32_calculator
        self.stream_data_generator = stream_data_generator
        self.stream_data_verifier = stream_data_verifier
        self.data_stream_logger = data_stream_logger
        self.received_file = None
        self.transport = transport

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
        if self.transport != None:
            self.transport.send_file(self.loaded_file.path)
        else:
            time.sleep(2)
        self.logger.log_event("[INFO]: File sent")

    def start_sending_stream_data(self, report_sending_data: Callable[[int], None]):
        self.logger.log_event("[INFO]: Start sending stream data")
        self.stream_data_generator.reset()
        while True:
            current_data = self.stream_data_generator.get_data()
            self.logger.log_event(f"[INFO]: Sending stream data: {current_data}")
            report_sending_data(current_data)
            if self.transport != None:
                self.transport.send_stream(current_data)
            time.sleep(1)

    def start_receiving_file(self):
        self.logger.log_event("[INFO]: Start receiving file")
        outdir = Path("logs/received")
        outdir.mkdir(parents=True, exist_ok=True)
        if self.transport != None:
            self.transport.receive_file(str(outdir))
            files = sorted(outdir.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
            if files:
                latest = files[0]
                self.received_file = self.file_storage.read_file(str(latest.resolve()))
            else:
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filepath = outdir / f"received_file_{timestamp}.bin"
                self.received_file = File(str(filepath.resolve()), b"")
                self.file_storage.save_file(self.received_file)
        else:
            dummy_file_content = bytes("AWOKWOKWOKWOKWOKWOKWOKWOKWOK", "utf-8")
            time.sleep(2)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filepath = outdir / f"received_file_{timestamp}.bin"
            self.received_file = File(str(filepath.resolve()), dummy_file_content)
            self.file_storage.save_file(self.received_file)

        self.logger.log_event(f"[INFO]: File received: {self.received_file.path}")
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
        self, report_receiving_data: Callable[[int, bool], None]
    ):
        self.logger.log_event("[INFO]: Start receiving stream data")
        self.data_stream_logger.start_session()
        self.stream_data_verifier.reset()
        if self.transport != None and hasattr(self.transport, "start_receiver_process"):
            proc = self.transport.start_receiver_process()
            try:
                for line in proc.stdout:
                    if "[TEKS]" in line and "STREAM:" in line:
                        part = line.split("STREAM:")[1].split()[0]
                        try:
                            val = int(part.strip())
                            is_valid = self.stream_data_verifier.verify(val)
                            report_receiving_data(val, is_valid)
                            self.data_stream_logger.log(data=val, is_valid=is_valid)
                            self.logger.log_event(f"[INFO]: Received stream data: {val} {'' if is_valid else '(INVALID)'}")
                        except ValueError:
                            pass
            finally:
                proc.terminate()
        else:
            temp_data = 0
            while True:
                time.sleep(1)
                received_data = temp_data + 1
                if temp_data % 5 == 0:
                    temp_data = temp_data + 1
                temp_data = (temp_data + 1) % 100
                is_valid = self.stream_data_verifier.verify(received_data)
                report_receiving_data(received_data, is_valid)
                self.data_stream_logger.log(data=received_data, is_valid=is_valid)
                self.logger.log_event(
                    f"[INFO]: Received stream data: {received_data} {'' if is_valid else '(INVALID)'}"
                )
