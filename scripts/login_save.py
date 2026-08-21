r"""ล็อกอินแล้วเซฟ session — ตรวจจาก "cookie ในเบราว์เซอร์" ไม่ใช่จาก URL

⚠️ ประวัติของบั๊กตัวนี้ อ่านก่อนแก้ ไม่งั้นจะวนกลับไปที่เดิม

   รอบที่ 1 (cli login) — เฝ้าดู page.url เฉย ๆ
       แต่ page.url ไม่อัปเดตตามที่ผู้ใช้เห็นบนจอ
       (2026-08-07: จอแสดงหน้าร้านเรียบร้อย แต่ page.url ค้างที่ /account/signin)
       ผลคือรอเก้อจนหมดเวลา ผู้ใช้ต้องล็อกอินซ้ำหลายรอบ

   รอบที่ 2 — แก้เป็น "นำทางไปหน้าคำสั่งซื้อจริงทุก 10 วินาที"
       แต่การนำทางไป "รีหน้าที่ผู้ใช้กำลังกรอกอยู่"
       ฟอร์มของ TikTok มีหลายขั้น (กรอกอีเมล -> ขอรหัส -> กรอกรหัส)
       โดนรีกลางคันแล้วต้องเริ่มใหม่ทุกรอบ ล็อกอินไม่มีวันสำเร็จ
       (เจอจริง 2026-08-08)

   รอบที่ 3 — แก้กลับเป็น "ดูเฉย ๆ" คืออ่าน page.url ไม่นำทาง
       บั๊กรอบที่ 1 กลับมาทันที และคราวนี้แย่กว่าเดิม เพราะโค้ดย้าย
       state.json เดิมไปเป็น .bak ตั้งแต่ต้น พอตรวจไม่ผ่านก็ไม่ได้เซฟตัวใหม่
       ผลคือ session หายทั้งเก่าและใหม่ ทั้งที่ผู้ใช้ล็อกอินสำเร็จแล้วจริง ๆ
       (เจอจริง 2026-08-17: tiktok_01/04/05 ล็อกอินเสร็จแต่เหลือแต่ไฟล์ .bak
        และเป็นคำอธิบายว่าทำไม TikTok ดูเหมือนหลุด session บ่อยผิดปกติมาตลอด)

   รอบนี้ — อ่าน cookie จาก context โดยตรง
       context.cookies() เป็นค่าที่เบราว์เซอร์รายงานสด ไม่ใช่ค่าที่ค้างอยู่ใน object
       และ "ไม่แตะหน้าเว็บเลย" จึงไม่ไปรีฟอร์มที่ผู้ใช้กำลังกรอก
       แก้ได้ทั้งบั๊กรอบที่ 1 และรอบที่ 2 พร้อมกัน
       ส่วน state.json เดิมจะไม่ถูกแตะจนกว่าจะเซฟตัวใหม่สำเร็จ

    python scripts\login_save.py --shop shopee_03
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.playwright_base import LOGIN_URL_HINTS   # noqa: E402
from src.adapters.registry import build_adapter            # noqa: E402
from src.core.config import load_config                    # noqa: E402

ORDERS = {
    "shopee": "/portal/sale/order",
    "tiktok": "/order",
    "lazada": "/apps/order/list?oldVersion=1",
}

# cookie ที่จะโผล่ก็ต่อเมื่อล็อกอินสำเร็จแล้วเท่านั้น
#
# ⚠️ ต้องเป็น cookie ที่ "ยืนยันตัวตน" จริง ไม่ใช่ cookie ที่เว็บตั้งให้ทุกคน
#    ตั้งแต่ยังไม่ล็อกอิน (เช่นตัวติดตามสถิติ) ไม่งั้นจะตีว่าล็อกอินแล้วตั้งแต่
#    หน้าแรก แล้วเซฟ session เปล่า ๆ ทับของดี
#
# ต้องเจอ "อย่างน้อย 1 ตัว" ในชุดของแพลตฟอร์มนั้น ถึงจะนับว่าล็อกอินแล้ว
# ⚠️ เทียบแบบ "ขึ้นต้นด้วย" ไม่ใช่ชื่อเป๊ะ ๆ
#    หลังบ้าน TikTok เติมท้ายชื่อ cookie ด้วย _tiktokseller (sessionid_tiktokseller ฯลฯ)
#    เทียบเป๊ะจึงไม่มีวันเจอ — ตรวจกับ session ที่ใช้งานได้จริงทั้ง 5 ร้าน ได้ 0 ตัวทุกร้าน
#    ผลคือล็อกอินสำเร็จแล้วสคริปต์ก็ยังบอกว่าไม่พบ แล้วหมดเวลาไปเฉย ๆ (เจอจริง 2026-08-18)
#    Shopee/Lazada ไม่โดนเพราะบังเอิญมีชื่ออื่นตรงอยู่ แต่ใช้กติกาเดียวกันให้หมดจะปลอดภัยกว่า
# ⚠️ ใส่เฉพาะ cookie ที่ "มีแล้วแปลว่าล็อกอินจริง" เท่านั้น
#    ห้ามใส่ตัวประกอบอย่าง sid_guard / uid_tt — พวกนี้ค้างอยู่ได้หลัง session ตายแล้ว
#    เคยหลวมจนรับ sid_guard_tiktokseller ตัวเดียวแล้วบอกว่าเก็บสำเร็จ
#    ทั้งที่ทดสอบสดขึ้น AUTH_EXPIRED (เจอจริง 2026-08-18 กับ tiktok_02)
AUTH_COOKIES = {
    "tiktok": ("sessionid",),          # sessionid_tiktokseller / sessionid_ss_tiktokseller
    "shopee": ("SPC_ST", "SPC_SC_SESSION"),
    "lazada": ("lzd_sid",),
}


def auth_hits(names: set[str], want: tuple[str, ...]) -> list[str]:
    """cookie ตัวไหนในเบราว์เซอร์ที่นับเป็นหลักฐานว่าล็อกอินแล้ว"""
    return sorted(n for n in names if any(n.startswith(w) for w in want))


def fresh_auth_hits(cookies: dict[str, str], baseline: dict[str, str],
                    want: tuple[str, ...]) -> list[str]:
    """เหมือน auth_hits แต่ไม่นับตัวที่ "มีอยู่ก่อนแล้วตั้งแต่เปิดหน้าต่าง"

    ⚠️ บั๊กรอบที่ 4 (เจอจริง 2026-08-21 กับ shopee_01)
       ก่อนเริ่มนับ สคริปต์ restore cookie จาก state เดิมเข้าเบราว์เซอร์ก่อนเสมอ
       ตัวที่รออยู่จึง "มีอยู่แล้ว" ตั้งแต่วินาทีแรก ผ่านเงื่อนไขนิ่ง 2 รอบ
       แล้วปิดหน้าต่างทิ้งภายใน ~6 วินาที — ผู้ใช้ไม่เคยได้ล็อกอินเลย
       แต่ไฟล์ที่เซฟมี cookie ครบตามชื่อ สคริปต์จึงรายงานว่าสำเร็จ
       (Shopee โดนหนักสุดเพราะ SPC_SC_SESSION ถูกตั้งให้คนที่ยังไม่ล็อกอินด้วย)

       การล็อกอินจริงทำให้แพลตฟอร์มออก token ใหม่เสมอ → ค่าต้องเปลี่ยน
       จึงนับเฉพาะตัวที่ "เพิ่งโผล่" หรือ "ค่าเปลี่ยนไปจากตอนเปิดหน้าต่าง"
       ไม่ต้องเดาว่า cookie ตัวไหนเป็นตัวจริง ซึ่งเดาผิดมา 3 รอบแล้ว
    """
    return sorted(
        n for n, v in cookies.items()
        if any(n.startswith(w) for w in want) and baseline.get(n) != v
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True)
    ap.add_argument("--wait", type=int, default=20, help="รอกี่นาที")
    args = ap.parse_args()

    cfg = load_config()
    s = cfg.shop(args.shop)
    adapter = build_adapter(s, cfg.settings)

    # ⚠️ ห้ามย้าย/ลบ state เดิมตรงนี้เด็ดขาด
    #    ของเดิมย้ายไปเป็น .bak ตั้งแต่ต้น พอตรวจไม่ผ่านก็ไม่ได้เซฟตัวใหม่
    #    ผลคือเหลือแต่ .bak ไม่มีตัวจริง = session หายทั้งเก่าและใหม่
    #    ทั้งที่ผู้ใช้ล็อกอินสำเร็จแล้ว (เจอจริง 2026-08-17 กับ tiktok_01/04/05)
    #
    #    ตอนนี้สำรองไว้ในหน่วยความจำเฉย ๆ แล้วค่อยเขียนทับตอนเซฟสำเร็จจริง
    #    ถ้าล้มกลางทาง ไฟล์เดิมยังอยู่ครบเหมือนไม่เคยรันสคริปต์นี้
    old_state: bytes | None = None
    if adapter.session_file.exists():
        old_state = adapter.session_file.read_bytes()
        print(f"  มี {adapter.session_file.name} เดิมอยู่ "
              f"({len(old_state)/1024:,.0f} KB) — จะไม่แตะจนกว่าจะเซฟตัวใหม่สำเร็จ")

    url = f"{adapter.base_url}{ORDERS.get(s.platform, '/')}"
    ok = False
    try:
        page = adapter._open_page(headed=True)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        want = AUTH_COOKIES.get(s.platform, ())
        print()
        print(f"  ร้าน : {s.display_name} ({s.shop_id})")
        print(f"  ล็อกอินในหน้าต่างที่เปิดขึ้นมาได้เลย — ไม่ต้องกดอะไรอื่น")
        print(f"  ระบบดูจาก cookie ในเบราว์เซอร์ ไม่แตะหน้าที่คุณกำลังกรอก")
        print(f"  รอ cookie: {', '.join(want)}")
        print(f"  (รอสูงสุด {args.wait} นาที)")
        print()

        # ── ค่าตั้งต้น: cookie ที่มีอยู่ "ก่อน" ผู้ใช้ลงมือ ────────────
        # ตัวเหล่านี้มาจาก state เดิมที่เพิ่ง restore เข้าไป ห้ามนับเป็นหลักฐาน
        try:
            baseline = {c.get("name", ""): c.get("value", "")
                        for c in adapter._context.cookies()}
        except Exception:                                # noqa: BLE001
            baseline = {}

        # ── ทางลัด: ถ้ายังล็อกอินอยู่แล้วจริง ไม่ต้องรบกวนผู้ใช้ ────────
        # ตรวจจาก URL หลัง goto — ถ้าไม่ถูกเด้งไปหน้า login แปลว่า session เดิมยังดี
        # ⚠️ page.url เชื่อได้แค่ทางเดียว: "ไม่ใช่หน้า login" = ผ่านจริง
        #    ส่วนกรณีที่อ่านได้เป็นหน้า login อาจเป็นค่าค้าง (บั๊กรอบที่ 1)
        #    จึงไม่ตัดสินว่าไม่ผ่าน แค่ตกไปรอผู้ใช้ล็อกอินตามปกติ ซึ่งปลอดภัยกว่า
        landed = (page.url or "").lower()
        if not any(h in landed for h in LOGIN_URL_HINTS) and auth_hits(
                set(baseline), want):
            print("  ✅ session เดิมยังใช้งานได้ (ไม่ถูกเด้งไปหน้าล็อกอิน) — เซฟทับให้เลย")
            ok = True

        # ── ตัวตรวจ: อ่าน cookie จาก context ─────────────────────────
        # context.cookies() ถามเบราว์เซอร์สด ๆ ต่างจาก page.url ที่เป็นค่าค้างใน object
        # และไม่แตะหน้าเว็บเลย จึงไม่ไปรีฟอร์มหลายขั้นของ TikTok
        deadline = time.time() + args.wait * 60
        stable = 0
        last_report = 0.0
        while not ok and time.time() < deadline:
            time.sleep(3)
            try:
                cookies = {c.get("name", ""): c.get("value", "")
                           for c in adapter._context.cookies()}
            except Exception as exc:                     # noqa: BLE001
                print(f"  หน้าต่างถูกปิด — ยังไม่ได้เซฟ ({str(exc)[:50]})")
                return 1

            names = set(cookies)
            hit = fresh_auth_hits(cookies, baseline, want)
            if hit:
                # ต้องนิ่ง 2 รอบติด กัน cookie ที่โผล่แวบเดียวระหว่างเปลี่ยนหน้า
                stable += 1
                if stable >= 2:
                    print(f"  ✅ พบ cookie ยืนยันตัวตนแล้ว: {', '.join(hit)}")
                    ok = True
                    break
            else:
                stable = 0
                if time.time() - last_report > 30:
                    print(f"  ยังไม่พบ cookie ยืนยันตัวตนตัวใหม่ (มี {len(names)} "
                          f"cookie แต่ยังเป็นชุดเดิมที่ restore เข้าไป)", flush=True)
                    last_report = time.time()

        if not ok:
            print("  หมดเวลารอ — ยังไม่ได้เซฟ (ไฟล์เดิมยังอยู่ครบ)")
            return 1

        # ── เซฟ แล้วตรวจว่าเซฟได้จริง ────────────────────────────────
        # เซฟ 2 รอบ เผื่อ cookie ที่แพลตฟอร์มตั้งเพิ่มหลัง redirect
        adapter._save_session()
        page.wait_for_timeout(4000)
        adapter._save_session()

        # ⚠️ ต้องตรวจว่าไฟล์ที่เขียนออกมามี cookie ยืนยันตัวตนจริง
        #    ไม่ใช่แค่ "มีไฟล์" — เคยได้ไฟล์ที่มี cookie แต่ไม่มีตัวที่ใช้ล็อกอิน
        try:
            saved = json.loads(adapter.session_file.read_text(encoding="utf-8"))
            got = {c.get("name", "") for c in saved.get("cookies", [])}
        except Exception as exc:                         # noqa: BLE001
            print(f"  ❌ อ่านไฟล์ที่เพิ่งเซฟไม่ได้ ({str(exc)[:60]})")
            got = set()

        if not auth_hits(got, want):
            print(f"  ❌ ไฟล์ที่เซฟไม่มี cookie ยืนยันตัวตน ({len(got)} cookie) — คืนไฟล์เดิม")
            if old_state is not None:
                adapter.session_file.write_bytes(old_state)
                print("     คืน state เดิมกลับแล้ว")
            else:
                adapter.session_file.unlink(missing_ok=True)
            return 1

        # ถึงตรงนี้แปลว่าเซฟสำเร็จจริง ค่อยเก็บของเดิมเป็น .bak
        if old_state is not None:
            adapter.session_file.with_suffix(".json.bak").write_bytes(old_state)
        print(f"  เก็บ session แล้ว {len(got)} cookie → {adapter.session_file.name}")
    finally:
        adapter.close()                                  # ปิดแบบสะอาด cookie ไม่หาย
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
