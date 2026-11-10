from transport import BaseTransport, SdrUdpTransport
from protocol import create_packets, decode_packet, ProtocolError


class StreamingEngine:
    __slots__ = ("transport", "is_opened", "is_receiver")

    transport: BaseTransport
    is_opened: bool
    is_receiver: bool

    def __init__(self, transport: BaseTransport | None = None):
        self.transport = transport if transport is not None else SdrUdpTransport()
        self.is_opened = False
        self.is_receiver = False

    def set_transport(self, transport: BaseTransport):
        self.close()
        self.transport = transport

    def open(self, is_receiver: bool = False):
        if not self.is_opened or self.is_receiver != is_receiver:
            self.close()
            self.transport.open(is_receiver=is_receiver)
            self.is_opened = True
            self.is_receiver = is_receiver

    def close(self):
        if self.is_opened:
            try:
                self.transport.close()
            except Exception:
                pass
            self.is_opened = False

    def send_stream_data(self, data: int) -> bool:
        """
        Kirim satu data angka stream (1-100) melalui transport menggunakan protocol packet.
        """
        if not self.is_opened:
            self.open(is_receiver=False)

        try:
            payload = str(data).encode("utf-8")
            packets = create_packets(payload)
            for packet in packets:
                self.transport.send(packet)
            return True
        except Exception:
            return False

    def receive_stream_data(
        self, timeout: float = 1.0
    ) -> tuple[int | None, str | None]:
        """
        Terima satu data stream dari transport.
        Returns: (received_number: int | None, error_message: str | None)
        - (val, None): Berhasil menerima angka
        - (None, None): Timeout / tidak ada data masuk
        - (None, error_str): Paket rusak / kesalahan protokol
        """
        if not self.is_opened:
            self.open(is_receiver=True)

        raw = self.transport.recv(timeout=timeout)
        if raw is None or not raw.strip():
            return None, None

        # Coba decode via protocol packet
        try:
            packet_info = decode_packet(raw)
            payload_str = packet_info["payload"].decode("utf-8")
            val = int(payload_str.strip())
            return val, None
        except ProtocolError as pe:
            # Fallback jika dikirim format integer polos
            try:
                val = int(raw.strip())
                return val, None
            except ValueError:
                return None, f"ProtocolError: {pe}"
        except Exception as e:
            try:
                val = int(raw.strip())
                return val, None
            except ValueError:
                return None, f"DecodeError: {e}"
