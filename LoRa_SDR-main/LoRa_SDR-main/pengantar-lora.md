# Pengantar LoRa dengan SDR

Bagaimana sinyal yang lebih lemah dari noise tetap bisa dibaca, dan bagaimana kita membangun modemnya sendiri dengan HackRF One.

## Mengapa LoRa ada

Sensor di sawah, gedung, atau sungai perlu mengirim sedikit data, sejauh mungkin, dengan baterai yang tahan bertahun-tahun. Wi-Fi cepat tetapi boros dan pendek jangkauannya. Seluler menjangkau jauh tetapi butuh operator dan biaya. LoRa memilih kompromi lain: kecepatannya sangat rendah, sebagai gantinya jangkauan bisa mencapai beberapa kilometer dengan daya miliwatt.

**LoRa** adalah lapisan fisik, yaitu cara mengubah bit menjadi sinyal radio. **LoRaWAN** adalah protokol jaringan di atasnya. Praktikum ini hanya membahas lapisan fisik, plus lapisan aplikasi sederhana buatan kita.

## Chirp: inti dari LoRa

LoRa memakai *Chirp Spread Spectrum*. Chirp adalah sinyal yang frekuensinya naik linear dari tepi bawah ke tepi atas bandwidth. Data dibawa oleh **titik awal** chirp. Saat mencapai tepi atas, frekuensi melompat ke tepi bawah dan terus naik.

```text
Chirp dasar (simbol 0)             Chirp berisi data (simbol > 0)

frekuensi                          frekuensi
+BW/2 |              /             +BW/2 |          /
      |            /                     |        /  
      |          /                       |      /            
   0  |        /                      0  |    /            
      |      /                           |  /                /
      |    /                             |/                /
      |  /                               |               /
-BW/2 |/                           -BW/2 |             /
      +--------------> waktu             +--------------> waktu
       1 simbol = 2^SF chip               titik awal = nilai data
```

Selisih frekuensi antara chirp berisi data dan chirp dasar tetap sepanjang simbol. Selisih itulah datanya.

### Cara penerima membacanya

Penerima mengalikan sinyal dengan chirp kebalikan (*dechirp*). Kemiringannya saling menghapus, sehingga tersisa satu nada murni. FFT lalu menemukan nada itu sebagai satu puncak tajam, dan nomor bin puncak adalah nilai simbol.

Energi yang tadinya tersebar di seluruh bandwidth terkumpul pada satu bin, sedangkan noise tetap tersebar. Karena itu sinyal terbaca meski lebih lemah dari noise. Satu simbol membawa SF bit dan terdiri atas 2^SF chip.

## Tiga parameter utama

| Parameter | Jika dinaikkan | Biaya |
|---|---|---|
| SF (7–12) | Jangkauan lebih jauh | Airtime kira-kira 2× per langkah |
| BW (125, 250 kHz) | Lebih cepat | Sensitivitas turun sekitar 3 dB per 2× |
| CR (4/5 – 4/8) | Lebih tahan bit error | Lebih banyak bit paritas |

### Menghitung airtime

Rumus untuk modem praktikum, dengan `L` panjang payload dalam byte dan `CR` bernilai 1–4:

```text
jumlah simbol = 20,25 + ceil(2 × (L + 2) / SF) × (4 + CR)
airtime       = jumlah simbol × 2^SF / BW
```

Contoh untuk payload 20 byte, BW 125 kHz, CR 4/5:

| SF | Airtime | Paket per jam (duty cycle 1%) | Laju bit efektif |
|---|---|---|---|
| 7 | 56,6 ms | 636 | 2,83 kbps |
| 8 | 102,9 ms | 349 | 1,55 kbps |
| 9 | 185,3 ms | 194 | 0,86 kbps |
| 10 | 370,7 ms | 97 | 0,43 kbps |
| 11 | 659,5 ms | 54 | 0,24 kbps |
| 12 | 1318,9 ms | 27 | 0,12 kbps |

Untuk konfigurasi lain, gunakan tool praktikum:

```bash
python3 lora_lab.py airtime --bytes 20 --sf 9 --bw 125e3 --cr 1
```

## Struktur frame

| Preamble | Sync word | Downchirp | Header | Payload + CRC16 |
|---|---|---|---|---|
| 8 upchirp | 2 simbol | 2,25 simbol | 8 simbol | panjang bervariasi |

- **Preamble** memberi tahu penerima ada frame datang.
- **Sync word** membedakan jaringan pada kanal yang sama.
- **Downchirp** membuat penerima bisa memisahkan offset frekuensi dari offset waktu.
- **Header** memuat panjang payload dan CR, dengan perlindungan paling kuat.

### Dari byte ke chirp

```text
byte → CRC16 → whitening → Hamming → interleave → Gray → chirp
```

Gray coding membuat puncak yang meleset satu bin hanya merusak satu bit, Hamming memperbaikinya, dan interleaver menyebar kerusakan satu simbol ke banyak codeword.

## SDR dan HackRF One

Pada *Software Defined Radio*, modulasi dilakukan oleh program. HackRF hanya mengubah deretan angka menjadi gelombang radio, dan sebaliknya. Karena itu modem yang sama bisa kita baca, ubah, dan perbaiki sendiri.

| Sifat HackRF | Akibat pada praktikum |
|---|---|
| Half-duplex | Hanya TX atau RX pada satu waktu, jadi harus bergantian |
| Data I/Q 8-bit | Rentang dinamis terbatas, sinyal terlalu kuat merusak bacaan |
| DC spike di frekuensi tengah | Sinyal digeser 300 kHz dari LO |
| Kristal sekitar ±20 ppm | Dua alat bisa berselisih puluhan kHz |

### Offset frekuensi

Pada 921 MHz, 20 ppm setara 18 kHz untuk satu alat, dan selisih dua alat bisa mencapai sekitar 37 kHz. Nilai ini besar dibanding BW 125 kHz, jadi harus dikoreksi.

Offset frekuensi menggeser puncak upchirp dan downchirp ke arah yang **sama**, sedangkan offset waktu menggesernya ke arah **berlawanan**. Dengan membandingkan keduanya, penerima memperoleh dua nilai itu sekaligus. Modem kita juga memakai nilai ppm untuk mengoreksi pergeseran clock simbol sepanjang paket.

## Jarak dan link budget

Daya yang diterima adalah daya kirim ditambah gain antena, dikurangi rugi lintasan. Rugi ruang bebas pada 921 MHz:

| Jarak | Rugi ruang bebas |
|---|---|
| 3 m | 41 dB |
| 30 m | 61 dB |
| 300 m | 81 dB |
| 3 km | 101 dB |

Di dalam gedung, setiap tembok menambah redaman kira-kira 5–15 dB, dan pantulan dapat membuat sinyal berubah hanya dengan menggeser antena beberapa puluh sentimeter.

| SF | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|
| Batas SNR (dB) | -7,5 | -10 | -12,5 | -15 | -17,5 | -20 |

Nilai tipikal dari datasheet Semtech. Modem SDR praktikum biasanya sedikit lebih rendah performanya.

## Aturan main di Indonesia

LPWAN di Indonesia memakai pita 920–923 MHz. Ringkasan Kepmen Kominfo No. 5 Tahun 2024 menyebut untuk end node: daya maksimum 100 mW EIRP, bandwidth maksimum 250 kHz, dan duty cycle uplink maksimum 1%. Periksa kembali naskah resminya untuk keperluan di luar praktikum.

Duty cycle 1% berarti 36 detik airtime per jam. Tool praktikum menegakkan batas ini otomatis. HackRF bukan perangkat bersertifikat, jadi gunakan hanya untuk praktikum, dengan daya rendah dan waktu singkat.

## Yang akan kita kerjakan

1. Menguji modem pada kanal simulasi.
2. Saling mengirim teks antar kelompok.
3. Mengukur pengaruh SF, BW, dan CR.
4. Mengirim stream sensor dan menghitung PDR.
5. Mengirim gambar dan suara melalui link yang sangat lambat.
6. Mengulangi semuanya dari ruangan yang berbeda.

Modem praktikum memakai teknik yang sama dengan LoRa, tetapi tidak kompatibel dengan chip LoRa komersial karena detail whitening, CRC, dan header-nya berbeda.

Panduan langkah demi langkah ada di [README.md](README.md).
