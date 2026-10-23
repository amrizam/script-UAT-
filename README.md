# Script UAT

UAT otomatis untuk **aplikasi web apa pun**. Script login sendiri ke aplikasi, membaca menu-menu yang tampil setelah
login, lalu menu yang dipilih menjadi modul UAT: tiap menu dibuka, diperiksa, dan di-screenshot. Hasilnya disusun menjadi
dokumen UAT `.docx` yang mengikuti format dokumen contoh.

## Persiapan (sekali saja)

1. Python 3.8+ dan Microsoft Edge atau Google Chrome (di Linux/macOS: Chrome/Chromium).
2. Pasang paket:

   ```
   py -m pip install -r requirements.txt
   ```

## Menjalankan

```
py uat.py
```

Isian ditanyakan satu per satu:

| Pertanyaan | Isi |
|---|---|
| Dokumen contoh | Path `.docx` yang formatnya diikuti (boleh drag & drop file ke terminal). Enter = template bawaan. |
| URL web | Alamat aplikasi, mis. `https://erp.perusahaan.co.id` (tanpa `https://` otomatis ditambahkan). |
| User | User / email login. |
| Password | Tidak tampil di layar. Bila login gagal, user & password ditanyakan lagi. |
| *(script login dan membaca menu)* | Menu aplikasi ditampilkan bernomor. |
| Modul yang di-UAT | `all`, nomor (`3`), rentang (`2-10`), nama menu (`Barang Masuk`) atau nama grup menu (`Master` = semua submenu Master), dipisah koma. |
| Simpan dokumen di | Folder hasil (bawaan `Documents\UAT`) atau path `.docx` lengkap. |

Contoh tampilan daftar modul:

```
Modul = menu yang terbaca setelah login:
    1. Login                      (login akun valid & akun salah)
    2. Dashboard                  /dashboard
    3. Master > Barang            /master/barang
    4. Master > Supplier          /master/supplier
    5. Transaksi > Barang Masuk   /trx/masuk
    6. Laporan                    /laporan
    7. Logout                     (logout & buka halaman setelah logout)
```

Semua isian juga bisa lewat argumen (yang tidak diisi akan ditanyakan):

```
py uat.py --template "D:\UAT\Contoh_UAT.docx" --url https://erp.perusahaan.co.id ^
          --user qa@perusahaan.co.id --modules all --output "D:\UAT\Hasil"
```

Password bisa lewat `--password` atau variabel lingkungan `UAT_PASSWORD`. Untuk dijalankan terjadwal tanpa pertanyaan,
tambahkan `--no-interactive`.

## Yang diuji

| Modul | Test case |
|---|---|
| Login | Login dengan akun valid; login dengan akun yang tidak terdaftar harus ditolak (pesan yang tampil dicatat) |
| Tiap menu | Menu diklik → halaman terbuka tanpa HTTP error / pesan error, tidak kosong. Dicatat: judul halaman, tabel (jumlah baris & kolom), isian/filter, tombol, error JavaScript. Screenshot halaman. |
| Logout | Klik logout → kembali ke halaman login; halaman aplikasi tidak bisa dibuka lagi tanpa login |

Hanya membuka halaman (tidak menyimpan/menghapus data). Link logout, ganti bahasa, file unduhan, link ke situs lain,
dan link berisi `delete/hapus` tidak dijadikan modul.

## Hasil

Di folder simpan dibuat:

- `UAT <Nama Aplikasi> 2026-10-23.docx` — dokumen UAT (bila sudah ada, diberi akhiran `(2)`, `(3)`, … agar tidak menimpa)
- `..._menu.json` — daftar menu yang terbaca setelah login
- `..._screenshots\` — screenshot tiap test case
- `..._hasil.json` — hasil mentah

Nama aplikasi diambil dari judul halaman login (ganti dengan `--title`).

Isi dokumen: Informasi Umum, Ruang Lingkup (dari menu yang dipilih), dan Test Case dibuat dari hasil pengujian.
Tujuan, Kriteria Penerimaan, tabel tanda tangan, Nama Proyek, Disusun/Ditinjau Oleh, dan Versi Dokumen diambil dari
dokumen contoh bila diberikan; tanpa dokumen contoh dipakai teks umum.

### Mengedit daftar menu

Bila ada menu yang tidak perlu atau namanya ingin diganti, edit `..._menu.json` (hapus item, ubah `title`), lalu:

```
py uat.py --menu-file "D:\UAT\Hasil\UAT ERP 2026-10-23_menu.json"
```

## Opsi lain

| Opsi | Fungsi |
|---|---|
| `--title`, `--project`, `--client`, `--author`, `--reviewer`, `--doc-version` | Isi judul, Informasi Umum, dan tanda tangan |
| `--id-prefix UAT-ERP` | Awalan Test Case ID (bawaan `UAT` → `UAT-001`) |
| `--headed` | Tampilkan jendela browser (untuk melihat jalannya tes) |
| `--browser PATH` | Path `msedge.exe` / `chrome.exe` bila tidak terdeteksi otomatis |
| `--help` | Semua opsi |

## Paket skenario (opsional)

Folder `packs/` berisi skenario yang ditulis manual per aplikasi (saat ini `portal-tenant`). Hanya dipakai bila diminta
dengan `--pack`, mis. `py uat.py --pack portal-tenant`; opsi `--lang`, `--allow-write`, `--account`, `--param`, dan
`--list-modules` khusus untuk mode ini.

## Struktur

```
uat.py                     CLI
uat_engine/explorer.py     mode generik: deteksi form login, baca menu, uji tiap menu
uat_engine/browser.py      kendali browser lewat Chrome DevTools Protocol
uat_engine/docbuilder.py   menyusun .docx mengikuti dokumen contoh
uat_engine/runner.py       mode --pack: menjalankan skenario JSON
packs/                     paket skenario (opsional)
templates/                 template bawaan
```
