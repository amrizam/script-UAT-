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
| Uji CRUD juga? | Enter / `y` = ya: di menu yang punya tombol Tambah, data uji ditambah, dilihat, diubah, lalu dihapus lagi. `n` = hanya membuka halaman. |
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

Password bisa lewat `--password` atau variabel lingkungan `UAT_PASSWORD`. Tambahkan `--crud` untuk uji CRUD. Untuk dijalankan
terjadwal tanpa pertanyaan, tambahkan `--no-interactive`.

## Yang diuji

| Modul | Test case |
|---|---|
| Login | Login dengan akun valid; login dengan akun yang tidak terdaftar harus ditolak (pesan yang tampil dicatat) |
| Tiap menu | Menu diklik → halaman terbuka tanpa HTTP error / pesan error, tidak kosong. Dicatat: judul halaman, tabel (jumlah baris & kolom), isian/filter, tombol, error JavaScript. Screenshot halaman. |
| Logout | Klik logout → kembali ke halaman login; halaman aplikasi tidak bisa dibuka lagi tanpa login |

Link logout, ganti bahasa, file unduhan, link ke situs lain, dan link berisi `delete/hapus` tidak dijadikan modul.

### Uji CRUD (`--crud` atau jawab "ya")

Untuk setiap menu yang punya tombol **Tambah / Add / Create / New / Baru / Buat / +**:

| Test case | Yang dilakukan |
|---|---|
| Menambah data (Create) | Klik Tambah → semua field diisi otomatis sesuai tipenya (teks, email, telepon, angka, tanggal, dropdown, radio, file wajib, editor teks) dengan data uji berpenanda unik, mis. `UAT1023111501` → Simpan → data harus tampil di daftar (dicari lewat kotak pencarian bila tidak ada di halaman pertama) |
| Validasi field wajib | Simpan form kosong → harus ditolak dengan pesan validasi. Hanya dijalankan bila form punya field wajib (`required` atau label bertanda `*`), supaya tidak membuat data kosong |
| Mencari & melihat detail (Read) | Cari data uji di daftar → klik Detail/Lihat → detail harus memuat data uji |
| Mengubah data (Update) | Klik Edit **di baris data uji** → isi diganti (`…U`) → Simpan → perubahan harus tampil di daftar |
| Menghapus data (Delete) | Klik Hapus **di baris data uji** → konfirmasi disetujui (dialog browser, SweetAlert, atau modal) → data harus hilang dari daftar |

Pengaman:

- Ubah dan hapus hanya diklik di baris yang berisi penanda data uji itu sendiri, dan form ubah hanya dikirim bila memang
  berisi penanda tersebut. Data lain di aplikasi tidak disentuh.
- Bila ada data uji yang gagal dihapus, di akhir tampil daftar **"PERHATIAN: data uji berikut mungkin masih ada"**
  (juga dicatat di `_hasil.json` → `data_uji_tersisa`) untuk dihapus manual.
- Sebaiknya dijalankan di server UAT/staging, karena tambah data bisa memicu proses lain di aplikasi (email, approval, stok).

Batasan: form yang butuh isian khusus (autocomplete yang harus dipilih dari hasil pencarian, captcha, OTP, upload dengan
format tertentu) bisa gagal tersimpan; hasilnya tercatat sebagai Fail beserta pesan validasi dari aplikasi.

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
