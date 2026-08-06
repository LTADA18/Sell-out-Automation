r"""ทดสอบว่าแต่ละแพลตฟอร์มยอมให้ Export ช่วงยาวแค่ไหน

Shopee รู้แล้วว่าได้ทีละ 1 เดือน — ตัวนี้ไว้เช็ค Lazada / TikTok
ผลลัพธ์กำหนดว่างานดึงย้อนหลัง 7 เดือนจะใช้เวลาเท่าไหร่

    python scripts\probe_range.py --shop tiktok_01 --months 7
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.models import AdapterError                 # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--shop", required=True)
ap.add_argument("--months", type=int, default=7)
args = ap.parse_args()

D_FROM = date(2026, 1, 1)
D_TO = date(2026, 7, 31) if args.months == 7 else date(2026, 1, 31)

cfg = load_config()
s = cfg.shop(args.shop)
adapter = build_adapter(s, cfg.settings)

print(f"ร้าน {s.shop_id} ({s.platform}) — ลองดึง {D_FROM} ถึง {D_TO}")
t0 = time.time()
try:
    orders = adapter.fetch_orders(D_FROM, D_TO)
    print(f"✅ สำเร็จ — {len(orders):,} ออเดอร์  ใช้เวลา {time.time() - t0:.0f} วินาที")
    if orders:
        days = {str(o.order_created_at)[:10] for o in orders if o.order_created_at}
        if days:
            print(f"   ครอบคลุมวันที่ {min(days)} ถึง {max(days)}  ({len(days)} วันที่มีออเดอร์)")
except AdapterError as exc:
    print(f"❌ {exc.error_type.value}: {exc}  (ใช้เวลา {time.time() - t0:.0f} วินาที)")
except Exception as exc:                                 # noqa: BLE001
    print(f"❌ {type(exc).__name__}: {exc}  (ใช้เวลา {time.time() - t0:.0f} วินาที)")
finally:
    adapter.close()
