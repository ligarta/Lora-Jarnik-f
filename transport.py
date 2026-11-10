import socket
import time
import subprocess
import sys
import shutil
from pathlib import Path

try:
    import serial
except ImportError:
    serial = None


class BaseTransport:
    def open(self, is_receiver=False):
        pass

    def send(self, data_str: str):
        pass

    def recv(self, timeout=1.0) -> str:
        pass

    def close(self):
        pass


class SdrUdpTransport(BaseTransport):
    def __init__(self, listen_ip="0.0.0.0", listen_port=5005, target_ip="127.0.0.1", target_port=5005):
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.target_ip = target_ip
        self.target_port = target_port
        self.sock = None

    def open(self, is_receiver=False):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if is_receiver:
            self.sock.bind((self.listen_ip, self.listen_port))
            self.sock.settimeout(2.0)
        else:
            self.sock.settimeout(2.0)

    def send(self, data_str: str):
        payload = (data_str + "\n").encode("utf-8")
        self.sock.sendto(payload, (self.target_ip, self.target_port))

    def recv(self, timeout=1.0) -> str:
        if timeout is not None:
            self.sock.settimeout(timeout)
        try:
            data, _ = self.sock.recvfrom(4096)
            return data.decode("utf-8", errors="ignore").strip()
        except (socket.timeout, BlockingIOError):
            return None

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


class SerialTransport(BaseTransport):
    def __init__(self, port="COM3", baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def open(self, is_receiver=False):
        if serial is None:
            raise ImportError("Pustaka 'pyserial' belum terinstall. Install dengan: pip install pyserial")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=1.0)
        time.sleep(1.0)

    def send(self, data_str: str):
        payload = (data_str + "\n").encode("utf-8")
        self.ser.write(payload)

    def recv(self, timeout=1.0) -> str:
        if self.ser.in_waiting > 0:
            line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            return line if line else None
        return None

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass


class LoraSdrTransport:
    def __init__(self, txvga=20, lna=24, vga=20, bw="125e3", sf=7):
        self.txvga = str(txvga)
        self.lna = str(lna)
        self.vga = str(vga)
        self.bw = str(bw)
        self.sf = str(sf)
        self.lab_script = self._find_lab_script()
        self.has_hackrf = shutil.which("hackrf_transfer") is not None
        self.iq_file = "logs/simulated_lora.iq"
        Path("logs").mkdir(parents=True, exist_ok=True)

    def _find_lab_script(self):
        base = Path(__file__).resolve().parent
        cand1 = base / "LoRa_SDR-main" / "LoRa_SDR-main" / "lora_lab.py"
        if cand1.exists():
            return cand1
        cand2 = base / "LoRa_SDR-main" / "lora_lab.py"
        if cand2.exists():
            return cand2
        cand3 = base / "lora_lab.py"
        if cand3.exists():
            return cand3
        return cand1

    def send_file(self, filepath: str):
        cmd = [
            sys.executable,
            str(self.lab_script),
            "send-file",
            str(filepath),
            "--txvga",
            self.txvga,
            "--bw",
            self.bw,
            "--sf",
            self.sf,
            "--no-duty-limit",
        ]
        if not self.has_hackrf:
            cmd += ["--iq", self.iq_file]
        return subprocess.run(cmd)

    def receive_file(self, outdir="logs/received"):
        Path(outdir).mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            str(self.lab_script),
            "recv",
            "--lna",
            self.lna,
            "--vga",
            self.vga,
            "--bw",
            self.bw,
            "--sf",
            self.sf,
            "--out",
            str(outdir),
        ]
        if not self.has_hackrf and Path(self.iq_file).exists():
            cmd += ["--iq", self.iq_file]
        return subprocess.run(cmd)

    def send_stream(self, val: int):
        cmd = [
            sys.executable,
            str(self.lab_script),
            "send-text",
            f"STREAM:{val}",
            "--txvga",
            self.txvga,
            "--bw",
            self.bw,
            "--sf",
            self.sf,
            "--no-duty-limit",
        ]
        if not self.has_hackrf:
            cmd += ["--iq", self.iq_file]
        return subprocess.run(cmd)

    def start_receiver_process(self, outdir="logs/received"):
        Path(outdir).mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            str(self.lab_script),
            "recv",
            "--lna",
            self.lna,
            "--vga",
            self.vga,
            "--bw",
            self.bw,
            "--sf",
            self.sf,
            "--out",
            str(outdir),
        ]
        if not self.has_hackrf and Path(self.iq_file).exists():
            cmd += ["--iq", self.iq_file]
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
