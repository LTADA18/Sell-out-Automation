# CLAUDE.md

ดึงคำสั่งซื้อจาก **หลังบ้านร้านค้าตัวเอง** ทุกวัน 06:00 น.
→ Excel 1 ไฟล์ต่อร้าน + Dashboard ดูสถานะการดึง

**ร้านที่มีจริงตอนนี้: 6 ร้าน** — Lazada 1 (กัปตัน เอกสตีล) + TikTok 5 / Shopee ยังไม่มีร้าน
โครงสร้างรองรับเพิ่มร้านได้ไม่จำกัด แค่เติมใน `shops.yaml`

ต่างจาก `pdp-scraper` (เก็บ spec สินค้าในตลาด) — ตัวนี้เก็บ **ออเดอร์ของร้านเราเอง**

## คำสั่งประจำ

```powershell
.\setup.ps1                                      # ติดตั้งครั้งเดียว
.\run_daily.ps1                                  # ดึงทุกร้าน (ข้อมูลของเมื่อวาน)
.\run_daily.ps1 -Shop lazada_01
.\.venv\Scripts\python.exe -m src.cli health     # เช็ค credential ไม่ดึงข้อมูล
.\.venv\Scripts\python.exe -m src.cli backfill --from 2026-07-01 --to 2026-07-31
.\.venv\Scripts\python.exe -m pytest -q
```

exit code ของ `run`: `0` = ครบทุกร้าน / `1` = มีร้าน FAILED / `2` = มีรอบอื่นรันอยู่

## สถานะ: จบ Phase 1 แล้ว

| เฟส | สิ่งที่มี | สถานะ |
|---|---|---|
| 1 | โครง + MockAdapter + Excel + run_log | ✅ เสร็จ |
| 3 | Playwright adapter (Lazada + TikTok) | ✅ โค้ดเสร็จ — **ยังไม่เคยรันจริงกับหลังบ้าน** |
| 2 | Streamlit dashboard | ⬜ (ข้ามไปก่อน) |
| 4 | Scheduler 06:00 | ⬜ |
| 5 | ค่าธรรมเนียม/settlement จาก Income report | ⬜ |

**ส่วนที่ยืนยันแล้วว่าถูก:** อ่านไฟล์ Export จริง → normalize → Excel (เทียบยอดกับหน้าเว็บตรงกัน)
**ส่วนที่ยังไม่ได้ทดสอบ:** ขั้นตอนคลิกในเบราว์เซอร์ (ต้องล็อกอินก่อน)

`shops.yaml` ยังตั้ง `adapter: mock` — เปลี่ยนเป็น `playwright` ทีละร้านหลังล็อกอินสำเร็จ

## ช่องว่างที่รู้ตัว

- **Lazada ไม่มี `province`** — `shippingCity` ถูก mask ต้องทำตารางรหัสไปรษณีย์→จังหวัดก่อน (TikTok ให้จังหวัดตรง ๆ ใช้ได้แล้ว)
- **Lazada ไม่มี `buyer_username`** — มีแต่ `customerName` ซึ่งเป็น PII เต็ม จึงไม่ map เข้ามา
- **ยังไม่มีค่าธรรมเนียม/settlement** ทั้ง 2 แพลตฟอร์ม (Phase 5)

## โครงสร้าง

```
config/shops.yaml         15 ร้าน (ไม่มีรหัสผ่าน) — adapter: mock|playwright|api
config/settings.yaml      timezone, lookback, retry, rate limit, include_pii
config/column_maps/*.yaml ชื่อคอลัมน์ในไฟล์ Export ของแต่ละแพลตฟอร์ม
src/adapters/             base.py (สัญญากลาง) + mock.py + registry.py
src/core/                 models / config / runner / exporter / status_store / privacy / logging
data/raw/                 response ดิบรายวัน (debug)
data/sessions/            cookie หลังบ้าน — ⚠️ ห้าม commit เด็ดขาด
data/status.db            run_log ที่ Dashboard อ่าน
output/{วันที่}/          Excel 15 ไฟล์
```

## กฎเหล็ก

1. **ห้ามสร้างตัวเลขขึ้นเอง** — ไม่มีข้อมูล = `"Null"` + เขียนเหตุผลลง `notes`
2. **`order_id` / `sku` / `tracking_no` เป็น string เสมอ** และ Excel ต้องบังคับ `number_format = "@"`
   เลข 19 หลักของ TikTok ถ้าหลุดเป็น int จะโดนปัดหลักท้ายทิ้ง
3. **ห้าม commit** `.env`, `data/sessions/`, `output/`, `*.db`
   ⚠️ ต่างจาก `pdp-scraper` ตรงที่ **ห้าม `git add -f` data/sessions/** — เป็น cookie หลังบ้าน
   หลุดแล้วคนอื่นเข้าจัดการร้านได้เลย
4. **`delay_between_shops` ห้ามต่ำกว่า 3 วินาที** (config validator บังคับไว้แล้ว)
5. **ห้ามพยายามผ่าน CAPTCHA / OTP / 2FA** — เจอเมื่อไหร่ให้หยุดร้านนั้น รายงาน `AUTH_REQUIRED`
6. **`.ps1` ต้องเซฟเป็น UTF-8 *with BOM*** — PowerShell 5.1 อ่านไฟล์ไม่มี BOM ด้วยโค้ดเพจ 874
   ภาษาไทยเพี้ยนแล้ว parser พังทั้งไฟล์
   ตรวจ: `[System.IO.File]::ReadAllBytes('run_daily.ps1')[0..2]` ต้องได้ `239 187 191`
7. ตอบเป็นภาษาไทย กระชับ เน้นตัวเลขและสิ่งที่ต้อง action

## สถานะการดึง (คือสิ่งที่ต้องดูว่า "ติดตรงไหน")

| status | สี | หมายความว่า |
|---|---|---|
| `SUCCESS` | 🟢 | ครบ |
| `PARTIAL` | 🟡 | ได้ไฟล์แต่ไม่สมบูรณ์ — ตอนนี้ใช้กับ `EMPTY_RESULT` |
| `FAILED` | 🔴 | **ต้องลงมือแก้** |
| `SKIPPED` | ⚪ | ปิดไว้เองใน `shops.yaml` ไม่ใช่ความพัง |
| `RUNNING` | 🔵 | กำลังทำงาน — ถ้าค้างเกิน 60 นาที `mark_stale_running()` จะเปลี่ยนเป็น FAILED |

**"ไม่มีออเดอร์วันนั้น" = `PARTIAL` ไม่ใช่ `FAILED`** — ร้านเล็กมีสิทธิ์ขายไม่ได้เลยสักชิ้น
ถ้าทำเป็นสีแดง สีแดงจะเฝือจนมองข้ามร้านที่พังจริง

### error_type ที่ห้าม retry

`AUTH_EXPIRED` / `AUTH_REQUIRED` / `NO_PERMISSION` — ยิงซ้ำก็ไม่ผ่าน มีแต่เสี่ยงโดนล็อกบัญชี
retry ได้เฉพาะ `RATE_LIMITED` / `TIMEOUT` / `NETWORK` (backoff 2s → 8s → 30s)

## สิ่งที่รู้จากไฟล์ Export จริง (อ่านก่อนเขียน adapter)

รายละเอียดเต็มอยู่ใน `config/column_maps/*.yaml` ส่วน `quirks` — สรุปตัวที่กัดบ่อย:

- **Lazada ไม่มีคอลัมน์ `quantity`** ออก 1 แถวต่อ 1 ชิ้น → ต้องยุบ group by `(orderNumber, sellerSku)` เอง
- **Lazada `orderItemId` ≠ `orderNumber`** — ใช้ `orderNumber` เป็น `order_id`
- **Lazada `shippingCity` ถูก mask** (`เ*n`) แต่ `shippingPostCode` ไม่ถูก mask → แปลงรหัสไปรษณีย์เป็นจังหวัด
- **Lazada `customerName` บางแถวไม่ถูก mask** โผล่ชื่อ-นามสกุลเต็ม + มีคอลัมน์ `nationalRegistrationNumber`
- **TikTok แถวที่ 2 เป็นคำอธิบายคอลัมน์** ไม่ใช่ข้อมูล → `data_start_row: 3`
- **ทั้ง 2 เจ้าไม่มีค่าคอมมิชชั่น/settlement ในรายงานออเดอร์** อยู่ในเมนูการเงิน (Phase 5)
- ไฟล์ Lazada ไม่ประกาศ dimension → ต้อง `ws.reset_dimensions()` ไม่งั้น openpyxl เห็นแค่ 1 คอลัมน์

## จุดที่คาดว่าจะพังใน Phase 3

1. **TikTok** — `pdp-scraper` เจอมาแล้วว่า TikTok บล็อกเบราว์เซอร์ที่ Playwright เปิดเอง
   ต้องใช้โหมด CDP (เปิด Chrome เองแล้วให้สคริปต์เกาะ) หลังบ้านน่าจะคุมเข้มกว่าหน้าสินค้าอีก
2. **cookie หลังบ้านหมดอายุเร็วกว่าฝั่งผู้ซื้อ** — ต้อง login ใหม่เป็นระยะ ดูหน้า Credential Health
3. **1 โปรไฟล์ Chrome = login ได้ทีละร้าน** → ต้องแยก `storage_state` ต่อร้าน 15 ไฟล์
4. **บางบัญชีไม่มีสิทธิ์ดูคำสั่งซื้อ** (เจอจริงกับ Lazada) → `NO_PERMISSION` ให้เจ้าของร้านเพิ่มสิทธิ์
   ร้านที่ยังแก้ไม่ได้ ให้ตั้ง `enabled: false` + `skip_reason` จะได้เป็นสีเทาไม่ใช่สีแดง
