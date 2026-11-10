# Hands-on: Belajar LoRa dengan SDR (HackRF One)

Dua kelompok, masing-masing satu HackRF One, saling bertukar teks, stream, dan multimedia dengan modulasi LoRa. Pengiriman dilakukan dari jarak dekat lalu dari ruangan berbeda.

Baca dulu materi pengantar: [`pengantar-lora.md`](pengantar-lora.md). Versi interaktifnya ada di `pengantar-lora.html`.

**Setelah praktikum ini kamu dapat:**

- Mengirim dan menerima data melalui radio menggunakan modem chirp buatan sendiri.
- Menjelaskan pengaruh SF, BW, dan CR terhadap kecepatan dan jangkauan.
- Membaca SNR dan offset frekuensi dari sinyal yang diterima.
- Merancang pengiriman data besar melalui link yang lambat dan dibatasi airtime.

**Durasi:** sekitar 3 jam.

| Bagian | Waktu |
|---|---|
| Persiapan dan uji tanpa radio | 20 menit |
| Lab 1–2: teks dan eksperimen parameter | 40 menit |
| Lab 3: stream | 25 menit |
| Lab 4: multimedia | 35 menit |
| Lab 5: jarak jauh (beda ruang) | 40 menit |
| Tantangan dan presentasi hasil | 20 menit |

---

## 1. Aturan wajib

1. **Selalu pasang antena sebelum memancarkan.** Memancar tanpa beban dapat merusak HackRF.
2. **Jaga jarak antena minimal 1 meter** antara dua HackRF, terutama saat `--amp` aktif. Sinyal yang terlalu kuat dapat merusak penerima.
3. **Tetap di pita 920–923 MHz** dengan bandwidth maksimum 250 kHz. Tool menolak nilai di luar itu.
4. **Patuhi anggaran airtime 36 detik per jam per HackRF** (duty cycle 1%). Tool menghitungnya otomatis. Opsi `--no-duty-limit` hanya untuk uji dengan kabel dan attenuator, atas izin instruktur.
5. **Mulai dari gain rendah**, naikkan hanya jika perlu.

> HackRF adalah perangkat eksperimen, bukan perangkat LoRa bersertifikat. Gunakan hanya untuk kegiatan praktikum ini, dengan daya rendah dan waktu pancar singkat.

---

## 2. Persiapan

### Yang dibutuhkan per kelompok

- 1 HackRF One dengan antena yang cocok untuk 900 MHz
- 1 laptop dengan Python 3.9 atau lebih baru
- Kabel USB data yang bagus (kabel yang buruk sering menjadi penyebab masalah)

### Instalasi

**macOS**

```bash
brew install hackrf ffmpeg
```

**Ubuntu / Debian**

```bash
sudo apt install hackrf ffmpeg python3-venv
```

**Semua sistem**

```bash
git clone <URL-REPO-INI> lora-sdr
cd lora-sdr
python3 -m venv .venv
source .venv/bin/activate
pip install numpy
```

### Pembagian peran

Kelompok A dan B memakai satu kanal yang sama, jadi semua perintah default sudah cocok.

| Pengaturan | Nilai |
|---|---|
| Frekuensi | `921.4 MHz` (default) |
| Sync word | `0x12` (default) |
| Bandwidth | `125 kHz` (default) |

**HackRF bersifat half-duplex:** satu alat hanya bisa memancar atau menerima pada satu waktu. Jadi harus bergantian, dan **penerima selalu dijalankan lebih dulu**.

---

## 3. Lab 0: Uji tanpa radio

Pastikan HackRF terbaca:

```bash
python3 lora_lab.py doctor
```

Uji modem pada kanal simulasi berisi noise, offset frekuensi, dan offset clock:

```bash
python3 lora_lab.py selftest
```

Hasil yang diharapkan adalah baris `LULUS` di akhir. Perhatikan kolom `SNR` yang negatif: **data tetap terbaca walau sinyal lebih lemah dari noise**. Inilah keunggulan utama LoRa.

**Pertanyaan**

1. Pada baris SNR terendah, berapa nilai SF yang dipakai?
2. Mengapa modem harus memperkirakan `ppm`? Lihat bagian offset frekuensi di materi pengantar.

---

## 4. Lab 1: Kirim teks

Antena berjarak 2–3 meter.

**Kelompok B (penerima), jalankan dulu:**

```bash
python3 lora_lab.py recv --lna 16 --vga 16
```

**Kelompok A (pengirim):**

```bash
python3 lora_lab.py send-text "Halo dari kelompok A" --txvga 10
```

Penerima akan menampilkan:

```text
[TEKS] Halo dari kelompok A  (SNR +12.3 dB, CFO -4.1 kHz (-4.4 ppm))
```

Lalu tukar peran.

Kalau tidak ada yang muncul, naikkan `--txvga` per 5 dB, lalu `--vga` dan `--lna`. Kalau muncul `CRC SALAH` pada jarak dekat, sinyal mungkin terlalu kuat, jadi turunkan gain.

**Catat:** SNR dan CFO dari lima kiriman. CFO seharusnya relatif tetap, karena itu selisih kristal kedua HackRF.

### Uji sync word

Penerima memakai sync word lain, lalu pengirim mengirim ulang:

```bash
python3 lora_lab.py recv --net 0x34 --lna 16 --vga 16
```

Apa yang terjadi? Mengapa ini berguna ketika banyak jaringan berbagi satu kanal?

---

## 5. Lab 2: Eksperimen SF, BW, dan CR

**Pengirim dan penerima harus memakai `--sf` dan `--bw` yang sama.** Nilai CR dibaca otomatis dari header.

Hitung airtime dulu sebelum mengirim, lalu kirim:

```bash
python3 lora_lab.py airtime --bytes 20 --sf 9
python3 lora_lab.py recv --sf 9 --lna 16 --vga 16                # penerima
python3 lora_lab.py send-text "uji parameter" --sf 9 --txvga 10  # pengirim
```

Lengkapi tabel berikut. Kirim 5 paket per konfigurasi dengan `--repeat 5`.

| SF | BW (kHz) | CR | Airtime 20 byte (ms) | Paket/jam maks | Diterima (dari 5) | SNR rata-rata |
|---|---|---|---|---|---|---|
| 7 | 125 | 1 | | | | |
| 7 | 250 | 1 | | | | |
| 9 | 125 | 1 | | | | |
| 10 | 125 | 1 | | | | |
| 7 | 125 | 4 | | | | |

**Pertanyaan**

1. Berapa kali lipat airtime ketika SF naik 1?
2. Apa keuntungan SF tinggi, dan apa biayanya?
3. Apa yang terjadi jika pengirim SF7 dan penerima SF9?

---

## 6. Lab 3: Stream

Data dikirim terus-menerus sebagai paket bernomor. Paket yang hilang tidak dikirim ulang, seperti pada telemetri sensor.

**Penerima:**

```bash
python3 lora_lab.py recv --lna 16 --vga 16
```

**Pengirim, mode sensor simulasi (satu paket tiap 5 detik):**

```bash
python3 lora_lab.py stream --sensor --interval 5 --txvga 10
```

**Atau mode ketik manual:** jalankan tanpa `--sensor`, lalu ketik pesan dan tekan Enter.

```bash
python3 lora_lab.py stream --txvga 10
```

Penerima menampilkan nomor urut dan jumlah paket hilang. Tekan `Ctrl-C` pada penerima untuk melihat nilai PDR (*Packet Delivery Ratio*).

**Tugas**

1. Hitung interval terkecil agar stream SF7/BW125 berukuran 30 byte tetap di bawah 1% duty cycle untuk operasi terus-menerus.
2. Ulangi perhitungan untuk SF10.
3. Selama stream berjalan, halangi antena dengan tangan atau tubuh. Amati perubahan SNR.

---

## 7. Lab 4: Multimedia

Link LoRa sangat lambat, jadi kuncinya adalah **mengecilkan data sebelum dikirim**.

### Siapkan file

**Gambar mini (sekitar 1–2 KB):**

```bash
ffmpeg -i foto.jpg -vf scale=96:-2 -q:v 20 kecil.jpg
```

**Suara pendek (5 detik, sekitar 4 KB):**

```bash
ffmpeg -i suara.wav -t 5 -ac 1 -ar 8000 -c:a libopus -b:a 6k -application voip kecil.ogg
```

### Kirim

Pakai BW 250 kHz untuk mempercepat. File dipotong menjadi paket 200 byte.

**Penerima:**

```bash
python3 lora_lab.py recv --bw 250e3 --lna 16 --vga 16 --out diterima
```

**Pengirim:**

```bash
python3 lora_lab.py send-file kecil.jpg --bw 250e3 --txvga 10
```

Bila semua paket tiba, file tersimpan di folder `diterima/` setelah CRC32-nya cocok.

### Jika ada paket hilang

Biarkan penerima tetap berjalan. Sekitar 3 detik setelah paket terakhir, penerima menampilkan:

```text
[FILE a4] belum lengkap. Minta kirim ulang dengan: --only 4,7
```

Kirim ulang hanya paket tersebut:

```bash
python3 lora_lab.py send-file kecil.jpg --bw 250e3 --txvga 10 --only 4,7
```

Mekanisme ini adalah **ARQ manual**: kamu sendiri yang menjadi jalur umpan baliknya.

**Tugas**

1. Hitung throughput: ukuran file dibagi total waktu dari awal kirim sampai file lengkap.
2. Bandingkan kualitas gambar pada `-q:v 5`, `20`, dan `31`, beserta jumlah paketnya.
3. Berapa file terbesar yang muat dalam anggaran 36 detik pada SF7/BW250?

---

## 8. Lab 5: Jarak jauh (beda ruang)

Satu kelompok pindah ke ruangan lain. Komunikasikan giliran melalui chat atau telepon.

| Skenario | SF / BW | `--txvga` | `--lna` | `--vga` | Catatan |
|---|---|---|---|---|---|
| Dekat, 2–3 m | 7 / 125 | 10 | 16 | 16 | Titik awal |
| Satu tembok | 7–9 / 125 | 25 | 24 | 24 | Naikkan SF bila gagal |
| Beda ruang, beberapa tembok | 9–10 / 125 | 35 | 32 | 30 | Tambah `--amp` di penerima bila perlu |
| Beda lantai atau koridor panjang | 10–12 / 125 | 40 | 32 | 36 | SF12 sangat boros airtime |

Nilai di atas hanya titik awal. Sesuaikan dengan kondisi gedung.

Naikkan gain secara bertahap: pertama `--vga`, lalu `--lna`, kemudian `--txvga`, dan `--amp` paling akhir.

**Contoh, beda ruang:**

```bash
# Penerima
python3 lora_lab.py recv --sf 10 --lna 32 --vga 30

# Pengirim
python3 lora_lab.py send-text "halo ruang sebelah" --sf 10 --txvga 35 --repeat 5
```

**Airtime multimedia di jarak jauh.** Satu paket penuh 206 byte memakan sekitar 1,0 detik pada SF9 dan 1,9 detik pada SF10, keduanya BW 125 kHz. Gambar 10 paket pada SF10 menghabiskan sekitar 19 detik, lebih dari separuh anggaran satu jam.

### Lembar pengukuran

Isi untuk setiap lokasi (minimal 3 lokasi).

| Lokasi | Jarak (m) | Jumlah tembok | SF | PDR (dari 10) | SNR rata-rata | SF terendah yang berhasil |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |

**Pertanyaan**

1. Pindah posisi antena beberapa puluh sentimeter. Apakah SNR berubah? Mengapa?
2. Berapa redaman tembok menurut data kalian?
3. Pada lokasi terjauh, konfigurasi mana yang memberi data terbanyak per detik tanpa kehilangan paket?

---

## 9. Tantangan

Kumpulkan bukti berupa log terminal atau file hasil terima.

| # | Tantangan | Syarat lulus | Poin |
|---|---|---|---|
| 1 | **Teks dua arah** | Kedua kelompok bertukar 5 pesan, semuanya utuh | 10 |
| 2 | **Stream andal** | 30 paket sensor beruntun dengan PDR ≥ 90% | 15 |
| 3 | **Gambar utuh** | Gambar ≤ 2 KB tiba dengan CRC32 cocok | 15 |
| 4 | **Suara** | Klip suara 3–5 detik tiba dan bisa diputar | 15 |
| 5 | **Beda ruang** | Selesaikan tantangan 1 dan 3 dari ruangan berbeda | 20 |
| 6 | **Hemat airtime** | Kelompok dengan total airtime terkecil untuk mengirim gambar yang sama dari beda ruang | 10 |
| 7 | **Bonus: ARQ otomatis** | Ubah kode agar penerima membalas daftar paket hilang lewat radio, dan pengirim mengirim ulang tanpa campur tangan manusia | 15 |
| 8 | **Bonus: FEC paket** | Tambah paket paritas XOR per 4 paket, sehingga satu paket hilang bisa dipulihkan tanpa kirim ulang | 15 |

**Petunjuk untuk tantangan 7:** ingat HackRF half-duplex. Kamu perlu protokol yang menentukan kapan setiap sisi berpindah antara TX dan RX, dan batas waktu ketika balasan tidak datang.

**Petunjuk untuk tantangan 8:** kerjakan di `file_packets()` dan `FileAssembler` pada `lora_lab.py`. Hitung apakah paritas lebih hemat airtime daripada kirim ulang pada PDR yang kalian ukur.

---

## 10. Pemecahan masalah

| Gejala | Kemungkinan penyebab | Solusi |
|---|---|---|
| `HackRF TIDAK terdeteksi` | Kabel USB atau port | Ganti kabel; gunakan port langsung, bukan hub |
| `hackrf_transfer gagal` | HackRF sedang dipakai proses lain | Hentikan proses lain, cabut dan pasang kembali USB |
| Penerima tidak menampilkan apa-apa | Penerima belum siap, atau SF/BW/net berbeda | Jalankan penerima lebih dulu; samakan parameter |
| `CRC SALAH` pada jarak dekat | Sinyal terlalu kuat | Turunkan `--txvga`, `--lna`, atau `--vga` |
| `CRC SALAH` pada jarak jauh | SNR terlalu rendah | Naikkan SF, naikkan CR (`--cr 4`), pindahkan antena |
| Paket hilang acak | Interferensi atau overflow USB | Tutup aplikasi berat; hindari hub USB |
| `Anggaran airtime habis` | Duty cycle 1% terpakai | Tunggu, kecilkan file, atau turunkan SF |

---

## 11. Struktur repo

```text
.
├── README.md            ← panduan ini
├── pengantar-lora.md    ← materi pengantar
├── pengantar-lora.html  ← materi pengantar versi interaktif
└── lora_lab.py          ← modem dan alat praktikum
```

Baca `lora_lab.py` dari atas ke bawah. Urutannya mengikuti alur sinyal: CRC dan whitening, Hamming, interleaver, chirp, lalu penerima.

**Keterbatasan modem ini**

- Ini modem untuk belajar. Modulasinya sama dengan LoRa, tetapi detail whitening, CRC, dan header berbeda, jadi **tidak bisa berkomunikasi dengan modul LoRa komersial** seperti SX1276.
- Tidak ada Low Data Rate Optimization, sehingga SF11–SF12 kurang tahan terhadap drift pada paket panjang.

**Untuk melangkah lebih jauh**, modem yang kompatibel dengan chip Semtech tersedia di [gr-lora_sdr](https://github.com/tapparelj/gr-lora_sdr) dari EPFL, berbasis GNU Radio.

## Referensi

- Semtech, *LoRa Modulation Basics* (AN1200.22) dan datasheet SX1276.
- Tapparel dkk., *An Open-Source LoRa Physical Layer Prototype on GNU Radio*, 2020.
- [Dokumentasi HackRF](https://hackrf.readthedocs.io/).
- Kementerian Komunikasi dan Informatika RI, KM No. 5 Tahun 2024 tentang standar teknis perangkat LPWAN non-seluler.
