#!/usr/bin/env python3
"""lora_lab.py - modem LoRa-style (CSS) untuk praktikum dengan HackRF One.

Hanya butuh: numpy + hackrf_transfer (hackrf-tools).

Lapisan PHY memakai teknik yang sama dengan LoRa: modulasi chirp (CSS),
preamble + sync word + downchirp, Gray mapping, interleaver diagonal,
Hamming FEC, whitening, dan header ber-reduced-rate.

CATATAN: ini modem untuk BELAJAR. Detail whitening/CRC/header berbeda dari
chip Semtech, jadi TIDAK kompatibel dengan modul LoRa komersial.

Alur TX: bytes -> CRC -> whitening -> Hamming -> interleave -> Gray -> chirp
Alur RX: kebalikannya, didahului deteksi preamble dan estimasi CFO/timing.
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

import numpy as np

# ------------------------------------------------------------------------
# Batas regulasi yang dipakai tool ini (pita LPWAN Indonesia, end node)
# ------------------------------------------------------------------------
FREQ_MIN, FREQ_MAX = 920.0e6, 923.0e6
MAX_BW = 250e3
DUTY_LIMIT = 0.01
DUTY_WINDOW = 3600.0
AIRTIME_LOG = Path.home() / ".lora_lab_airtime.json"

SAMPLE_RATE = 2_000_000
IF_OFFSET = 300_000  # sinyal digeser dari LO agar menjauhi DC spike HackRF
RX_OS = 4            # oversampling di sisi penerima
PREAMBLE_LEN = 8
DETECT_RATIO = 6.5
MAX_PAYLOAD = 255


# ------------------------------------------------------------------------
# Lapisan bit: CRC, whitening, Hamming, Gray, interleaver
# ------------------------------------------------------------------------
def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def whiten(data):
    """XOR dengan urutan LFSR agar data berulang tidak membentuk pola."""
    lfsr, out = 0xFF, bytearray()
    for b in data:
        out.append(b ^ lfsr)
        for _ in range(8):
            fb = ((lfsr >> 7) ^ (lfsr >> 5) ^ (lfsr >> 4) ^ (lfsr >> 3)) & 1
            lfsr = ((lfsr << 1) | fb) & 0xFF
    return bytes(out)


def gray_encode(v):
    return v ^ (v >> 1)


def gray_decode(g):
    v = 0
    while g:
        v ^= g
        g >>= 1
    return v


def hamming_encode(nibble, cr):
    """nibble 4-bit -> codeword (4+cr) bit. cr=1..4 berarti rate 4/5..4/8."""
    d = [(nibble >> i) & 1 for i in (3, 2, 1, 0)]
    if cr == 1:
        parity = [d[0] ^ d[1] ^ d[2] ^ d[3]]
    else:
        parity = [d[0] ^ d[1] ^ d[2], d[1] ^ d[2] ^ d[3],
                  d[0] ^ d[1] ^ d[3], d[0] ^ d[2] ^ d[3]][:cr]
    word = 0
    for bit in d + parity:
        word = (word << 1) | bit
    return word


HAMMING_TABLE = {cr: [hamming_encode(n, cr) for n in range(16)] for cr in range(1, 5)}


def hamming_decode(word, cr):
    """Pilih nibble dengan codeword terdekat (jarak Hamming terkecil)."""
    table = HAMMING_TABLE[cr]
    return min(range(16), key=lambda n: bin(table[n] ^ word).count("1"))


def nibbles_of(data):
    out = []
    for b in data:
        out += [b & 0xF, b >> 4]
    return out


def bytes_of(nibbles):
    return bytes(nibbles[i] | (nibbles[i + 1] << 4) for i in range(0, len(nibbles) - 1, 2))


def interleave(nibbles, cr, rows):
    """Satu blok: `rows` codeword -> (4+cr) simbol @ `rows` bit, secara diagonal."""
    n = 4 + cr
    words = [hamming_encode(x, cr) for x in nibbles]
    symbols = []
    for j in range(n):
        s = 0
        for i in range(rows):
            bit = (words[(i + j) % rows] >> (n - 1 - j)) & 1
            s |= bit << i
        symbols.append(s)
    return symbols


def deinterleave(symbols, cr, rows):
    n = 4 + cr
    words = [0] * rows
    for j in range(n):
        for i in range(rows):
            if (symbols[j] >> i) & 1:
                words[(i + j) % rows] |= 1 << (n - 1 - j)
    return [hamming_decode(w, cr) for w in words]


def header_nibbles(length, cr):
    h = [length >> 4, length & 0xF, cr]
    chk = (0x5A + 7 * h[0] + 11 * h[1] + 13 * h[2]) & 0xFF
    return h + [chk >> 4, chk & 0xF]


# ------------------------------------------------------------------------
# Encoder: payload -> daftar nilai simbol
# ------------------------------------------------------------------------
def encode_symbols(payload, sf, cr):
    if not 1 <= len(payload) <= MAX_PAYLOAD:
        raise ValueError(f"panjang payload harus 1..{MAX_PAYLOAD} byte")
    # Header: reduced rate (SF-2 bit per simbol) dan CR 4/8 agar paling tahan.
    rows = sf - 2
    h = header_nibbles(len(payload), cr)
    h += [0] * (rows - len(h))
    symbols = [gray_decode(s) * 4 for s in interleave(h, 4, rows)]

    body = whiten(payload + crc16(payload).to_bytes(2, "big"))
    nib = nibbles_of(body)
    nib += [0] * (-len(nib) % sf)
    for i in range(0, len(nib), sf):
        symbols += [gray_decode(s) for s in interleave(nib[i:i + sf], cr, sf)]
    return symbols


def payload_symbol_count(length, sf, cr):
    nib = 2 * (length + 2)
    return int(np.ceil(nib / sf)) * (4 + cr)


def sync_symbols(net):
    return [(net >> 4) * 8, (net & 0xF) * 8]


# ------------------------------------------------------------------------
# Modulator
# ------------------------------------------------------------------------
def chirp(sf, os_rate, symbol=0):
    """Upchirp yang digeser siklik sejauh `symbol` chip.

    Fase analitik x^2/(2N) - x/2 membuat dua bagian chirp (sebelum dan sesudah
    wrap) sefase pada laju chip, sehingga semua energi jatuh ke satu bin FFT.
    """
    N = 1 << sf
    t = np.arange(N * os_rate) / os_rate
    base = np.exp(2j * np.pi * (t * t / (2 * N) - t / 2))
    return np.roll(base, -symbol * os_rate)


def modulate(payload, sf, bw, cr, net, fs=SAMPLE_RATE):
    os_rate = int(fs / bw)
    up = chirp(sf, os_rate)
    down = np.conj(up)
    parts = [up] * PREAMBLE_LEN
    parts += [chirp(sf, os_rate, s) for s in sync_symbols(net)]
    parts += [down, down, down[: len(down) // 4]]
    parts += [chirp(sf, os_rate, s) for s in encode_symbols(payload, sf, cr)]
    return np.concatenate(parts)


def airtime(length, sf, bw, cr):
    n = PREAMBLE_LEN + 2 + 2.25 + 8 + payload_symbol_count(length, sf, cr)
    return n * (1 << sf) / bw


def to_iq8(x, offset_start=0, fs=SAMPLE_RATE):
    """Geser ke IF lalu ubah ke format 8-bit I/Q milik HackRF."""
    n = np.arange(offset_start, offset_start + len(x))
    y = x * np.exp(2j * np.pi * IF_OFFSET * n / fs) * 100
    return np.column_stack((y.real, y.imag)).astype(np.int8).tobytes()


# ------------------------------------------------------------------------
# Demodulator streaming
# ------------------------------------------------------------------------
class Decimator:
    """Geser sinyal dari IF ke baseband, filter, lalu turunkan sample rate."""

    def __init__(self, factor, fs=SAMPLE_RATE):
        self.factor, self.fs, self.n, self.offset = factor, fs, 0, 0
        taps = 8 * factor + 1
        t = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(t * 0.8 / factor) * np.hamming(taps)
        self.h = h / h.sum()
        self.tail = np.zeros(taps - 1, complex)

    def process(self, x):
        n = np.arange(self.n, self.n + len(x))
        self.n += len(x)
        x = x * np.exp(-2j * np.pi * IF_OFFSET * n / self.fs)
        joined = np.concatenate((self.tail, x))
        self.tail = joined[-(len(self.h) - 1):]
        y = np.convolve(joined, self.h, "valid")
        out = y[self.offset:: self.factor]
        self.offset = (self.offset - len(y)) % self.factor
        return out


def wrap(v, N):
    return (v + N / 2) % N - N / 2


class Receiver:
    """Mencari frame di aliran sampel. feed() mengembalikan frame yang valid."""

    def __init__(self, sf, bw, net, freq=921.4e6, fs=SAMPLE_RATE, verbose=False):
        self.sf, self.bw, self.net, self.freq = sf, bw, net, freq
        self.verbose = verbose
        self.N = 1 << sf
        self.os = RX_OS
        self.L = self.N * self.os
        self.up = chirp(sf, self.os)
        self.chip_ref = np.conj(chirp(sf, 1))
        # Low-pass sebesar bandwidth sinyal, dipakai setelah CFO dihapus.
        taps = 6 * self.os + 1
        t = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(t * 1.15 / self.os) * np.hamming(taps)
        self.chip_lpf = h / h.sum()
        self.down = np.conj(self.up)
        self.dec = Decimator(int(fs / bw / self.os), fs)
        self.buf = np.zeros(0, complex)
        self.pos = 0
        self.run = []

    # --- dechirp ---
    def fold(self, seg, ref, pad=1):
        """Dechirp + FFT; energi alias dijumlahkan ke N*pad bin."""
        spec = np.abs(np.fft.fft(seg * np.conj(ref), self.L * pad)) ** 2
        return spec.reshape(self.os, self.N * pad).sum(axis=0)

    def peak(self, seg, ref):
        p = self.fold(seg, ref)
        k = int(np.argmax(p))
        noise = (p.sum() - p[k]) / (self.N - 1)
        return k, p[k] / (noise + 1e-12)

    def fine_peak(self, starts, ref):
        """Posisi puncak dengan resolusi 1/4 bin, dirata-rata beberapa simbol."""
        total = sum(self.fold(self.buf[s:s + self.L], ref, 4) for s in starts)
        return int(np.argmax(total)) / 4

    def feed(self, chunk):
        self.buf = np.concatenate((self.buf, self.dec.process(chunk)))
        frames = []
        while self.pos + self.L <= len(self.buf):
            if len(self.run) < 5:  # kalau sudah 5, frame sedang menunggu sampel
                k, ratio = self.peak(self.buf[self.pos:self.pos + self.L], self.up)
                near = self.run and min((k - self.run[-1][1]) % self.N,
                                        (self.run[-1][1] - k) % self.N) <= 1
                if ratio > DETECT_RATIO and (near or not self.run):
                    self.run.append((self.pos, k))
                elif ratio > DETECT_RATIO:
                    self.run = [(self.pos, k)]
                else:
                    self.run = []
            if len(self.run) >= 5:
                result = self.try_frame()
                if result == "more":
                    break
                self.run = []
                if result is not None:
                    frames.append(result)
                    self.pos = result["end"]
                    continue
            self.pos += self.L
        self.trim()
        return frames

    def trim(self):
        keep = self.run[0][0] if self.run else self.pos
        keep = max(0, keep - 8 * self.L)
        if keep:
            self.buf = self.buf[keep:]
            self.pos -= keep
            self.run = [(p - keep, k) for p, k in self.run]

    def try_frame(self):
        p0, k_up = self.run[0]
        if p0 + 18 * self.L > len(self.buf):
            return "more"
        # Cari bin downchirp pada beberapa jendela setelah preamble.
        best, k_down = 0, None
        for i in range(5, 16):
            s = p0 + i * self.L
            k, ratio = self.peak(self.buf[s:s + self.L], self.down)
            if ratio > best:
                best, k_down = ratio, k
        if k_down is None or best < DETECT_RATIO:
            return None
        # up = cfo - d, down = cfo + d. Pembagian 2 punya ambiguitas N/2,
        # jadi kedua kandidat diuji dan yang CFO-nya kecil dicoba dulu.
        half = ((k_down - k_up) % self.N) / 2
        cands = sorted([(half, ), (half + self.N / 2, )],
                       key=lambda c: abs(wrap(k_up + c[0], self.N)))
        # Geser setengah simbol identik dengan geser BW/2, jadi kandidat yang
        # salah bisa lolos sync dan header. CRC yang menentukan pemenangnya.
        fallback = None
        for (d, ) in cands:
            r = self.decode_at(p0 + int(round(d * self.os)))
            if r == "more" or (r is not None and r["crc_ok"]):
                return r
            fallback = fallback or r
        return fallback

    def decode_at(self, base):
        L, N, os_rate = self.L, self.N, self.os
        # Temukan batas downchirp pertama: dua jendela berurutan kuat.
        B = None
        for j in range(0, 16):
            s = base + j * L
            if s + 2 * L > len(self.buf):
                break
            first = self.peak(self.buf[s:s + L], self.down)[1]
            second = self.peak(self.buf[s + L:s + 2 * L], self.down)[1]
            if first > DETECT_RATIO and second > DETECT_RATIO and \
               first > self.peak(self.buf[s:s + L], self.up)[1]:
                B = s
                break
        if B is None or B - 7 * L < 0:
            return None

        # Estimasi halus CFO dan timing pada jendela yang sudah sejajar.
        ups = [B - (2 + j) * L for j in range(1, 6)]
        downs = [B, B + L]
        ku = wrap(self.fine_peak(ups, self.up), N)
        kd = wrap(self.fine_peak(downs, self.down), N)
        cfo = wrap((ku + kd) / 2, N)
        delta = wrap(kd - ku, N) / 2
        if abs(delta) > 1.5:
            return None
        B += int(round(delta * os_rate))
        cfo_hz = cfo * self.bw / N
        # Clock HackRF sama-sama menurunkan RF dan sample clock, sehingga
        # offset frekuensi juga memberi tahu seberapa cepat simbol bergeser.
        ppm = cfo_hz / self.freq
        step = L * (1 - ppm)

        margin = (len(self.chip_lpf) - 1) // 2

        def demod(index_from_b):
            s = int(round(B + index_from_b * step))
            seg = self.buf[s - margin:s + L + margin]
            seg = seg * np.exp(-2j * np.pi * cfo / N * np.arange(len(seg)) / os_rate)
            chips = np.convolve(seg, self.chip_lpf, "valid")[::os_rate]
            p = np.abs(np.fft.fft(chips * self.chip_ref)) ** 2
            return int(np.argmax(p)), p

        for i, want in enumerate(sync_symbols(self.net)):
            got, _ = demod(i - 2)
            if min((got - want) % N, (want - got) % N) > 2:
                return None

        # Header
        if B + (2.25 + 9) * L > len(self.buf):
            return "more"
        rows = self.sf - 2
        sym = [(((demod(2.25 + i)[0] + 2) // 4) % (1 << rows)) for i in range(8)]
        h = deinterleave([gray_encode(s) for s in sym], 4, rows)
        length, cr = (h[0] << 4) | h[1], h[2]
        if header_nibbles(length, cr)[:5] != h[:5] or not 1 <= cr <= 4 or length == 0:
            return None

        # Payload
        count = payload_symbol_count(length, self.sf, cr)
        end = B + (2.25 + 8 + count + 1) * step
        if end + L > len(self.buf):
            return "more"
        n_block = 4 + cr
        nib, powers = [], []
        for b in range(count // n_block):
            block = []
            for i in range(n_block):
                k, p = demod(2.25 + 8 + b * n_block + i)
                powers.append((p.max(), (p.sum() - p.max()) / (N - 1)))
                block.append(gray_encode(k))
            nib += deinterleave(block, cr, self.sf)
        body = whiten(bytes_of(nib)[: length + 2])
        payload, crc = body[:length], int.from_bytes(body[length:], "big")
        sig = np.mean([p[0] for p in powers])
        noise = np.mean([p[1] for p in powers])
        snr = 10 * np.log10(max(sig - noise, 1e-9) / (noise * N) * 1.15)
        result = {"end": int(B + (2.25 + 8 + count) * step), "payload": payload,
                  "crc_ok": crc16(payload) == crc, "snr_db": float(snr),
                  "cfo_hz": float(cfo_hz), "ppm": float(ppm * 1e6),
                  "sf": self.sf, "cr": cr}
        return result


# ------------------------------------------------------------------------
# Lapisan aplikasi
#   T + teks                                 pesan teks
#   S + seq(2) + data                        stream
#   F + fid + seq(2) + total(2) + potongan   file (seq 0 = metadata)
# ------------------------------------------------------------------------
CHUNK = 200


def file_packets(path):
    data = Path(path).read_bytes()
    crc = zlib.crc32(data)
    fid = crc & 0xFF
    chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    total = len(chunks)
    name = Path(path).name.encode()[:80]
    meta = crc.to_bytes(4, "big") + len(data).to_bytes(4, "big") + name
    packets = {0: b"F" + bytes([fid]) + (0).to_bytes(2, "big") + total.to_bytes(2, "big") + meta}
    for i, c in enumerate(chunks, 1):
        packets[i] = b"F" + bytes([fid]) + i.to_bytes(2, "big") + total.to_bytes(2, "big") + c
    return packets


class FileAssembler:
    def __init__(self, outdir):
        self.outdir = Path(outdir)
        self.files = {}
        self.last_new = None  # waktu paket file terakhir, untuk laporan otomatis

    def add(self, p):
        fid, seq, total = p[1], int.from_bytes(p[2:4], "big"), int.from_bytes(p[4:6], "big")
        f = self.files.setdefault(fid, {"total": total, "chunks": {}, "meta": None, "done": False})
        self.last_new = time.time()
        if seq == 0:
            f["meta"] = p[6:]
        else:
            f["chunks"][seq] = p[6:]
        print(f"[FILE {fid:02x}] paket {seq}/{total}  terkumpul {len(f['chunks'])}/{total}"
              f"  metadata={'ada' if f['meta'] else 'belum'}", flush=True)
        if f["done"] or not f["meta"] or len(f["chunks"]) < total:
            return
        data = b"".join(f["chunks"][i] for i in range(1, total + 1))
        crc = int.from_bytes(f["meta"][:4], "big")
        name = Path(f["meta"][8:].decode(errors="replace")).name
        if zlib.crc32(data) != crc:
            print(f"[FILE {fid:02x}] CRC file SALAH", flush=True)
            return
        self.outdir.mkdir(parents=True, exist_ok=True)
        out = self.outdir / name
        out.write_bytes(data)
        f["done"] = True
        print(f"[FILE {fid:02x}] SELESAI -> {out} ({len(data)} byte, CRC32 cocok)", flush=True)

    def report(self):
        for fid, f in self.files.items():
            if f["done"]:
                continue
            missing = [i for i in range(1, f["total"] + 1) if i not in f["chunks"]]
            if not f["meta"]:
                missing.insert(0, 0)
            print(f"[FILE {fid:02x}] belum lengkap. Minta kirim ulang dengan: "
                  f"--only {','.join(map(str, missing))}", flush=True)


# ------------------------------------------------------------------------
# Anggaran airtime (duty cycle)
# ------------------------------------------------------------------------
def airtime_used():
    try:
        rows = json.loads(AIRTIME_LOG.read_text())
    except (OSError, ValueError):
        rows = []
    now = time.time()
    return [r for r in rows if now - r[0] < DUTY_WINDOW]


def airtime_charge(seconds, enforce):
    rows = airtime_used()
    used = sum(r[1] for r in rows)
    budget = DUTY_LIMIT * DUTY_WINDOW
    if enforce and seconds > budget:
        raise SystemExit(f"Kiriman ini butuh {seconds:.1f} s airtime, melebihi anggaran {budget:.0f} s/jam. "
                         f"Kecilkan data, turunkan SF, atau pakai BW 250 kHz.")
    if enforce and used + seconds > budget:
        wait = 0
        freed = 0
        for t, s in rows:
            freed += s
            wait = t + DUTY_WINDOW - time.time()
            if used - freed + seconds <= budget:
                break
        raise SystemExit(f"Anggaran airtime habis: terpakai {used:.1f} s dari {budget:.0f} s/jam, "
                         f"kiriman ini butuh {seconds:.1f} s. Coba lagi {wait / 60:.0f} menit lagi "
                         f"atau kecilkan data.")
    rows.append([time.time(), seconds])
    AIRTIME_LOG.write_text(json.dumps(rows))
    print(f"Airtime kiriman ini {seconds:.2f} s; total 1 jam terakhir "
          f"{used + seconds:.1f}/{budget:.0f} s", flush=True)


# ------------------------------------------------------------------------
# HackRF
# ------------------------------------------------------------------------
def stop_process(proc):
    """Tutup pipe dulu: hackrf_transfer bisa tertahan menulis ke pipe yang penuh."""
    for pipe in (proc.stdin, proc.stdout):
        try:
            if pipe:
                pipe.close()
        except OSError:
            pass
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def lo_freq(args):
    return int(args.freq - IF_OFFSET)


def tx_cmd(args, source):
    return ["hackrf_transfer", "-t", source, "-f", str(lo_freq(args)), "-s", str(SAMPLE_RATE),
            "-a", "1" if args.amp else "0", "-x", str(args.txvga)]


def transmit(args, packets):
    """Kirim daftar payload berurutan dalam satu sesi hackrf_transfer."""
    gap = np.zeros(int(0.02 * SAMPLE_RATE), complex)
    lead = np.zeros(int(0.15 * SAMPLE_RATE), complex)
    frames = [lead]
    total = 0.0
    for p in packets:
        frames += [modulate(p, args.sf, args.bw, args.cr, args.net), gap]
        total += airtime(len(p), args.sf, args.bw, args.cr)
    if not args.iq:  # simulasi ke berkas tidak memakai anggaran airtime
        airtime_charge(total, not args.no_duty_limit)
    iq = to_iq8(np.concatenate(frames + [lead]))
    if args.iq:
        Path(args.iq).write_bytes(iq)
        print(f"IQ disimpan ke {args.iq} ({len(iq)} byte), tidak dipancarkan")
        return
    with tempfile.NamedTemporaryFile(suffix=".iq", delete=False) as f:
        f.write(iq)
        name = f.name
    try:
        r = subprocess.run(tx_cmd(args, name), capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("hackrf_transfer gagal:\n" + r.stderr)
    finally:
        os.unlink(name)
    print(f"Terkirim {len(packets)} paket di {args.freq / 1e6:.3f} MHz "
          f"(SF{args.sf}, BW {args.bw / 1e3:.0f} kHz, CR 4/{4 + args.cr}, net 0x{args.net:02X})")


def receive_loop(args):
    rx = Receiver(args.sf, args.bw, args.net, args.freq, verbose=args.verbose)
    assembler = FileAssembler(args.out)
    stats = {"ok": 0, "bad": 0, "first": None, "last": None, "lost": 0, "seq": None, "stream": 0}

    def handle(frame):
        payload = frame["payload"]
        info = f"SNR {frame['snr_db']:+.1f} dB, CFO {frame['cfo_hz'] / 1e3:+.1f} kHz ({frame['ppm']:+.1f} ppm)"
        if not frame["crc_ok"]:
            stats["bad"] += 1
            print(f"[CRC SALAH] {len(payload)} byte  {info}", flush=True)
            return
        stats["ok"] += 1
        now = time.time()
        stats["first"] = stats["first"] or now
        stats["last"] = now
        kind = payload[:1]
        if kind == b"T":
            print(f"[TEKS] {payload[1:].decode(errors='replace')}  ({info})", flush=True)
        elif kind == b"S" and len(payload) >= 3:
            seq = int.from_bytes(payload[1:3], "big")
            if stats["seq"] is not None:
                stats["lost"] += max(0, (seq - stats["seq"] - 1) & 0xFFFF)
            stats["seq"] = seq
            stats["stream"] += 1
            print(f"[STREAM #{seq} hilang={stats['lost']}] "
                  f"{payload[3:].decode(errors='replace')}  ({info})", flush=True)
        elif kind == b"F" and len(payload) >= 6:
            assembler.add(payload)
        else:
            print(f"[RAW] {payload.hex()}  ({info})", flush=True)

    def finish():
        assembler.report()
        print(f"\nRingkasan: {stats['ok']} frame benar, {stats['bad']} frame CRC salah")
        sent = stats["stream"] + stats["lost"]
        if sent:
            print(f"Stream: {stats['stream']} diterima, {stats['lost']} hilang, "
                  f"PDR {100 * stats['stream'] / sent:.1f}%")

    def consume(raw):
        iq = np.frombuffer(raw, np.int8)
        iq = iq[: len(iq) & ~1].astype(np.float32) / 128
        for frame in rx.feed(iq[0::2] + 1j * iq[1::2]):
            handle(frame)

    if args.iq:
        data = Path(args.iq).read_bytes()
        for i in range(0, len(data), 1 << 18):
            consume(data[i:i + (1 << 18)])
        consume(bytes(int(4 * SAMPLE_RATE * 0.05)))
        finish()
        return

    cmd = ["hackrf_transfer", "-r", "-", "-f", str(lo_freq(args)), "-s", str(SAMPLE_RATE),
           "-a", "1" if args.amp else "0", "-l", str(args.lna), "-g", str(args.vga)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    print(f"Mendengarkan {args.freq / 1e6:.3f} MHz, SF{args.sf}, BW {args.bw / 1e3:.0f} kHz, "
          f"net 0x{args.net:02X}. Tekan Ctrl-C untuk berhenti.", flush=True)
    deadline = time.time() + args.duration if args.duration else None
    try:
        while deadline is None or time.time() < deadline:
            raw = proc.stdout.read(1 << 17)
            if not raw:
                print("hackrf_transfer berhenti. Cek koneksi HackRF.")
                break
            consume(raw)
            # Setelah 3 detik tanpa paket file baru, tampilkan yang masih kurang.
            if assembler.last_new and time.time() - assembler.last_new > 3:
                assembler.report()
                assembler.last_new = None
    except KeyboardInterrupt:
        pass
    finally:
        stop_process(proc)
        finish()


def stream_tx(args):
    """Pancarkan paket secara kontinu; saat kosong HackRF mengirim nol."""
    q = queue.Queue()
    seq_box = [0]

    def push(text):
        p = b"S" + (seq_box[0] & 0xFFFF).to_bytes(2, "big") + text.encode()[:MAX_PAYLOAD - 3]
        seq_box[0] += 1
        q.put(p)

    def sensor():
        t0 = time.time()
        while True:
            t = time.time() - t0
            push(f"suhu={27 + 2 * np.sin(t / 10):.1f} lembap={70 + 5 * np.cos(t / 7):.0f}")
            time.sleep(args.interval)

    def lines():
        for line in sys.stdin:
            if line.strip():
                push(line.rstrip("\n"))
        q.put(None)

    threading.Thread(target=sensor if args.sensor else lines, daemon=True).start()
    proc = subprocess.Popen(tx_cmd(args, "-"), stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = 0
    idle = bytes(1 << 14)
    print("Streaming berjalan. Tekan Ctrl-C untuk berhenti." +
          ("" if args.sensor else " Ketik baris lalu Enter."), flush=True)
    try:
        while True:
            try:
                p = q.get_nowait()
            except queue.Empty:
                proc.stdin.write(idle)
                continue
            if p is None:
                break
            airtime_charge(airtime(len(p), args.sf, args.bw, args.cr), not args.no_duty_limit)
            x = modulate(p, args.sf, args.bw, args.cr, args.net)
            proc.stdin.write(to_iq8(x, n))
            n += len(x)
            print(f"-> paket #{int.from_bytes(p[1:3], 'big')}: {p[3:].decode(errors='replace')}", flush=True)
        proc.stdin.write(bytes(1 << 20))
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        stop_process(proc)


# ------------------------------------------------------------------------
# Uji mandiri tanpa radio
# ------------------------------------------------------------------------
def channel(x, snr_db, ppm, freq, rng, fs=SAMPLE_RATE, bw=125e3):
    """Kanal simulasi: offset clock + CFO + AWGN pada SNR terhadap bandwidth sinyal."""
    eps = ppm * 1e-6
    n = np.arange(len(x)) * (1 + eps)
    xi = np.interp(n, np.arange(len(x)), x.real) + 1j * np.interp(n, np.arange(len(x)), x.imag)
    t = np.arange(len(xi))
    y = xi * np.exp(2j * np.pi * (eps * freq) * t / fs)
    y = np.concatenate((np.zeros(int(rng.integers(5000, 60000)), complex), y, np.zeros(200000, complex)))
    t = np.arange(len(y))
    y = y * np.exp(2j * np.pi * IF_OFFSET * t / fs)
    sigma = np.sqrt((fs / bw) * 10 ** (-snr_db / 10) / 2)
    return y + sigma * (rng.normal(size=len(y)) + 1j * rng.normal(size=len(y)))


def selftest(args):
    rng = np.random.default_rng(7)
    cases = [(7, 125e3, 1, 10, 0), (7, 125e3, 1, 0, 12), (7, 125e3, 4, -3, -18),
             (7, 250e3, 1, 5, 18), (8, 125e3, 2, -3, 15), (9, 125e3, 1, -6, -15),
             (10, 250e3, 1, -8, 10)]
    fail = 0
    print(f"{'SF':>3} {'BW':>6} {'CR':>4} {'SNR':>5} {'ppm':>5}  hasil  SNR-est  ppm-est")
    for sf, bw, cr, snr, ppm in cases:
        ok, n, est = 0, args.packets, []
        for _ in range(n):
            payload = bytes(rng.integers(0, 256, 180, dtype=np.uint8).tolist())
            y = channel(modulate(payload, sf, bw, cr, 0x12), snr, ppm, args.freq, rng, bw=bw)
            rx = Receiver(sf, bw, 0x12, args.freq)
            found = []
            for i in range(0, len(y), 1 << 16):
                found += rx.feed(y[i:i + (1 << 16)])
            if any(f["payload"] == payload and f["crc_ok"] for f in found):
                ok += 1
                est.append((found[0]["snr_db"], found[0]["ppm"]))
        fail += ok < n
        e = np.mean(est, axis=0) if est else (float("nan"), float("nan"))
        print(f"{sf:>3} {bw / 1e3:>5.0f}k 4/{4 + cr} {snr:>5} {ppm:>5}  {ok}/{n}   {e[0]:+6.1f}  {e[1]:+6.1f}")
    print("LULUS" if not fail else f"ADA {fail} KASUS GAGAL")
    if fail:
        raise SystemExit(1)


def doctor(_args):
    if not shutil.which("hackrf_transfer"):
        raise SystemExit("hackrf_transfer tidak ditemukan. Pasang hackrf-tools dahulu.")
    r = subprocess.run(["hackrf_info"], capture_output=True, text=True)
    print(r.stdout + r.stderr)
    print("OK: HackRF terdeteksi." if "Serial number" in r.stdout else
          "HackRF TIDAK terdeteksi. Cek kabel USB.")


# ------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------
def add_phy(p):
    p.add_argument("--freq", type=float, default=921.4e6, help="frekuensi tengah Hz (default 921.4e6)")
    p.add_argument("--sf", type=int, default=7, choices=range(7, 13), help="spreading factor")
    p.add_argument("--bw", type=float, default=125e3, choices=[125e3, 250e3], help="bandwidth Hz")
    p.add_argument("--cr", type=int, default=1, choices=range(1, 5), help="1..4 = 4/5..4/8")
    p.add_argument("--net", type=lambda s: int(s, 0), default=0x12, help="sync word (0x12..0xF8)")
    p.add_argument("--amp", action="store_true", help="aktifkan RF amp +14 dB")
    p.add_argument("--iq", help="pakai berkas IQ sebagai ganti radio")


def add_tx(p):
    add_phy(p)
    p.add_argument("--txvga", type=int, default=20, help="gain TX 0-47 dB")
    p.add_argument("--no-duty-limit", action="store_true", help="hanya untuk uji kabel/simulasi")


def check_args(args):
    if hasattr(args, "freq"):
        lo = args.freq - args.bw / 2
        hi = args.freq + args.bw / 2
        if lo < FREQ_MIN or hi > FREQ_MAX:
            raise SystemExit("Frekuensi harus di dalam pita 920-923 MHz.")
        if args.bw > MAX_BW:
            raise SystemExit("Bandwidth maksimum 250 kHz.")
        if not (args.net >> 4 and args.net & 0xF):
            raise SystemExit("--net: kedua digit hex harus bukan nol, contoh 0x12 atau 0x34.")


def main():
    ap = argparse.ArgumentParser(description="Modem LoRa-style untuk HackRF One")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="cek HackRF").set_defaults(fn=doctor)

    p = sub.add_parser("selftest", help="uji modem pada kanal simulasi")
    p.add_argument("--packets", type=int, default=3)
    p.add_argument("--freq", type=float, default=921.4e6)
    p.set_defaults(fn=selftest, bw=125e3, net=0x12)

    p = sub.add_parser("airtime", help="hitung airtime satu paket")
    p.add_argument("--bytes", type=int, default=20)
    p.add_argument("--sf", type=int, default=7)
    p.add_argument("--bw", type=float, default=125e3)
    p.add_argument("--cr", type=int, default=1)
    p.set_defaults(fn=lambda a: print(
        f"{a.bytes} byte, SF{a.sf}, BW {a.bw / 1e3:.0f} kHz, CR 4/{4 + a.cr}: "
        f"{airtime(a.bytes, a.sf, a.bw, a.cr) * 1e3:.1f} ms; "
        f"maksimum {int(36 / airtime(a.bytes, a.sf, a.bw, a.cr))} paket/jam pada duty cycle 1%"))

    p = sub.add_parser("send-text", help="kirim teks")
    add_tx(p)
    p.add_argument("text")
    p.add_argument("--repeat", type=int, default=1)
    p.set_defaults(fn=lambda a: transmit(a, [b"T" + a.text.encode()[:254]] * a.repeat))

    p = sub.add_parser("send-file", help="kirim file (dipotong per 200 byte)")
    add_tx(p)
    p.add_argument("path")
    p.add_argument("--only", help="kirim ulang nomor paket tertentu, contoh 0,3,7")

    def send_file(a):
        pk = file_packets(a.path)
        chosen = sorted(pk) if not a.only else [int(x) for x in a.only.split(",")]
        print(f"{Path(a.path).stat().st_size} byte -> {len(pk) - 1} paket data + 1 metadata; kirim {len(chosen)}")
        transmit(a, [pk[i] for i in chosen])

    p.set_defaults(fn=send_file)

    p = sub.add_parser("stream", help="kirim stream dari keyboard atau sensor simulasi")
    add_tx(p)
    p.add_argument("--sensor", action="store_true")
    p.add_argument("--interval", type=float, default=5.0, help="detik antar paket sensor")
    p.set_defaults(fn=stream_tx)

    p = sub.add_parser("recv", help="terima semua jenis data")
    add_phy(p)
    p.add_argument("--lna", type=int, default=24, help="gain LNA 0-40 dB, kelipatan 8")
    p.add_argument("--vga", type=int, default=20, help="gain VGA 0-62 dB, kelipatan 2")
    p.add_argument("--out", default="diterima", help="folder file hasil terima")
    p.add_argument("--duration", type=float, help="berhenti setelah N detik")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=receive_loop)

    args = ap.parse_args()
    check_args(args)
    args.fn(args)


if __name__ == "__main__":
    main()
