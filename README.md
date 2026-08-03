# ระบบดึงยอดคำสั่งซื้อ

ดึงคำสั่งซื้อจากหลังบ้าน Lazada / TikTok Shop / Shopee ทุกวัน 06:00 น. (เวลาไทย)
→ Excel 1 ไฟล์ต่อ 1 ร้าน + Dashboard ดูว่าร้านไหนดึงสำเร็จ ร้านไหนติดตรงไหน

**ร้านปัจจุบัน 6 ร้าน**: Lazada 1 + TikTok 5 (Shopee ยังไม่มีร้าน)

> **ตอนนี้อยู่ Phase 1** — ทำงานได้ครบทั้งระบบแต่ยังใช้ **ข้อมูลปลอม** (MockAdapter)
> ยังไม่ต่อกับหลังบ้านจริง ดู [CLAUDE.md](CLAUDE.md) สำหรับสถานะแต่ละเฟส

---

## ติดตั้ง (ครั้งเดียว)

```powershell
.\setup.ps1
```

ต้องมี Python 3.11 ขึ้นไป (เครื่องนี้ใช้ 3.14.6) สคริปต์จะสร้าง `.venv` + ลงไลบรารี + สร้าง `.env` ให้

## ใช้งาน

```powershell
.\run_daily.ps1                     # ดึงทุกร้าน (ข้อมูลของ "เมื่อวาน")
.\run_daily.ps1 -Shop lazada_01     # ดึงร้านเดียว
.\run_daily.ps1 -Platform lazada    # ดึงทั้งแพลตฟอร์ม
.\run_daily.ps1 -Date 2026-08-01    # ระบุวันที่ของรอบเอง
```

คำสั่งอื่น (เรียกผ่าน python ตรง ๆ):

```powershell
.\.venv\Scripts\python.exe -m src.cli health
.\.venv\Scripts\python.exe -m src.cli backfill --from 2026-07-01 --to 2026-07-31
.\.venv\Scripts\python.exe -m src.cli run --shop lazada_01 --from 2026-07-25 --to 2026-08-01
```

## ผลลัพธ์

```
output/2026-08-03/lazada_lazada_01_2026-08-03.xlsx
output/_archive/2026-08-03/...          ไฟล์เดิมถูกย้ายมาที่นี่ก่อนถูกเขียนทับ
data/raw/lazada/lazada_01/2026-08-02.json
data/status.db                          run_log ที่ Dashboard อ่าน
logs/run_2026-08-03.jsonl               log แบบ JSON lines (token ถูก mask แล้ว)
```

**Excel แต่ละไฟล์มี 3 sheet**

| sheet | มีอะไร |
|---|---|
| `Orders` | 1 แถว = 1 รายการสินค้าในออเดอร์ (order line) 32 คอลัมน์ |
| `Summary` | สรุปรายวัน: จำนวนออเดอร์ / ชิ้น / ยอดขาย / ยกเลิก / AOV / แยกตามสถานะ |
| `Meta` | เวลาที่ดึง ช่วงวันที่ จำนวนแถว สถานะ เวอร์ชันสคริปต์ |

## ตั้งค่า

### `config/shops.yaml` — รายชื่อร้าน

```yaml
- shop_id: lazada_01
  platform: lazada
  adapter: mock          # mock | playwright | api  ← เปลี่ยนบรรทัดนี้เพื่อสลับวิธีดึง
  display_name: "ชื่อร้าน"
  enabled: true
```

**ร้านที่ยังไม่มีสิทธิ์ดูคำสั่งซื้อ** ให้ปิดไว้แบบนี้ จะขึ้นสีเทา (ข้าม) ไม่ใช่สีแดง (พัง):

```yaml
  enabled: false
  skip_reason: "บัญชีมีสิทธิ์แค่จัดการโฆษณา — รอเจ้าของเพิ่มสิทธิ์"
```

### `config/settings.yaml` — ที่แก้บ่อย

| ค่า | ตอนนี้ | ความหมาย |
|---|---|---|
| `fetch.lookback_days` | `1` | ดึงย้อนหลังกี่วัน — `1` = วันต่อวัน |
| `fetch.refresh_status_days` | `0` | ไล่อัปเดตไฟล์ย้อนหลังกี่วัน — ตั้ง `7` เมื่ออยากให้ออเดอร์ที่ถูกยกเลิกทีหลังอัปเดตตาม |
| `privacy.include_pii` | `false` | `true` = เก็บชื่อผู้ซื้อเต็มลง Excel |
| `rate_limit.delay_between_shops` | `[3, 7]` | หน่วงระหว่างร้าน (วินาที) ต่ำกว่า 3 ไม่ได้ |

### ข้อมูลส่วนบุคคล (PDPA)

ค่าเริ่มต้น `include_pii: false` หมายถึง Excel จะได้:

- `buyer_username` → mask เป็น `s*****i`
- `province` → **เก็บไว้** (วิเคราะห์ได้โดยไม่ระบุตัวตน)
- ชื่อ-นามสกุล / เบอร์โทร / ที่อยู่ / เลขบัตรประชาชน → **ไม่เขียนลงไฟล์เลย**

ไฟล์ดิบใน `data/raw/` ยังเก็บของเดิมไว้ debug และอยู่ใน `.gitignore` แล้ว

---

## แก้ปัญหาที่เจอบ่อย

**`❌ มีรอบที่กำลังรันอยู่`**
รอบก่อนยังไม่จบ หรือเครื่องดับกลางรอบ ระบบจะยึด lock คืนเองถ้าเก่าเกิน 6 ชม.
อยากปลดเดี๋ยวนั้น: ลบไฟล์ `data/run.lock`

**`⚠️ เจอแถวค้างสถานะ RUNNING`**
ปกติ — แปลว่ารอบก่อนถูกปิดกลางคัน ระบบปรับเป็น FAILED ให้แล้ว

**ภาษาไทยใน `.ps1` เพี้ยนเป็น `เธตเธขเธง`**
ไฟล์ถูกเซฟแบบไม่มี BOM ตรวจด้วย:

```powershell
[System.IO.File]::ReadAllBytes('run_daily.ps1')[0..2]
```

ต้องได้ `239 187 191` ถ้าไม่ใช่ ให้เซฟใหม่เป็น **UTF-8 with BOM**

**เปิด Excel แล้ว `order_id` กลายเป็น `1.23457E+18`**
ไม่ควรเกิด — exporter บังคับ `number_format = "@"` ไว้แล้ว ถ้าเจอแปลว่ามีบั๊ก แจ้งได้เลย

**ร้านขึ้น `AUTH_EXPIRED`**
cookie หมดอายุ ต้อง login ใหม่ร้านนั้น (คำสั่ง `login` จะเปิดใช้ใน Phase 3)
**ห้าม retry** — ยิงซ้ำมีแต่เสี่ยงโดนล็อกบัญชี

**ร้านขึ้น `NO_PERMISSION`**
บัญชีที่ login มีสิทธิ์ไม่พอ ต้องให้เจ้าของร้านเพิ่มสิทธิ์ **จัดการคำสั่งซื้อ** ให้
(เจอมาแล้วกับ Lazada — บัญชีที่มีแค่สิทธิ์ *จัดการโฆษณา* เปิดหน้าคำสั่งซื้อไม่ได้)

---

## ทดสอบ

```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 44 เทส
```

ครอบคลุม: exporter (text format / ไม่บวกยอดซ้ำ / archive), runner (retry, fail isolation, lock),
status_store (แถวค้าง RUNNING), adapter (normalize, ข้อมูลคงที่), PDPA masking
