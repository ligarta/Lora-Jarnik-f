from datetime import datetime
from pathlib import Path


class DataStreamLogger:
    __slots__ = "log_path"

    log_path: Path | None

    def __init__(self):
        self.log_path = None

    def start_session(self):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        self.log_path = Path(f"logs/received_stream_{timestamp}_log.csv")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write("timestamp,received_data,notes\n")

    def log(self, data: int, is_valid: bool, notes: str = ""):
        if self.log_path == None:
            self.start_session()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not notes:
            notes = "INVALID" if not is_valid else "OK"
        # Escape quotes if comma is present in notes
        cleaned_notes = f'"{notes}"' if "," in notes else notes
        log_line = f"{timestamp},{data},{cleaned_notes}\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(log_line)
