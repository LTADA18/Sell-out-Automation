"""หน้าบ้านคำสั่ง — python -m src.cli <command>"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

import click

from src.adapters.registry import build_adapter
from src.core.config import PROJECT_ROOT, load_config
from src.core.logging_setup import setup_logging
from src.core.runner import AlreadyRunningError, Runner, run_lock, summarize
from src.core.status_store import StatusStore

DATE_FMT = "%Y-%m-%d"


def _parse(value: str | None, field: str) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, DATE_FMT).date()
    except ValueError:
        raise click.BadParameter(f"{field} ต้องเป็นรูปแบบ YYYY-MM-DD (ได้มา: {value})")


@click.group()
def cli() -> None:
    """ดึงคำสั่งซื้อจากหลังบ้าน Shopee / Lazada / TikTok Shop"""


@cli.command()
@click.option("--all", "all_shops", is_flag=True, help="ดึงทุกร้านใน shops.yaml")
@click.option("--shop", help="ดึงร้านเดียว เช่น lazada_01")
@click.option("--platform", type=click.Choice(["shopee", "lazada", "tiktok"]), help="ดึงทั้งแพลตฟอร์ม")
@click.option("--date", "run_date_s", help="วันที่ของรอบ (YYYY-MM-DD) ค่าเริ่มต้น=วันนี้")
@click.option("--from", "date_from_s", help="ใช้คู่กับ --to เพื่อระบุช่วงเอง")
@click.option("--to", "date_to_s", help="ใช้คู่กับ --from")
def run(
    all_shops: bool,
    shop: str | None,
    platform: str | None,
    run_date_s: str | None,
    date_from_s: str | None,
    date_to_s: str | None,
) -> None:
    """ดึงข้อมูลแล้วออก Excel"""
    if not any([all_shops, shop, platform]):
        raise click.UsageError("ต้องระบุอย่างน้อยหนึ่งอย่าง: --all / --shop / --platform")

    cfg = load_config()
    run_date = _parse(run_date_s, "--date") or date.today()

    # --from/--to = สั่งช่วงเอง แปลงเป็น lookback_days ให้ runner ใช้ต่อ
    d_from, d_to = _parse(date_from_s, "--from"), _parse(date_to_s, "--to")
    if d_from and d_to:
        if d_from > d_to:
            raise click.BadParameter("--from ต้องไม่หลัง --to")
        cfg.settings.fetch.lookback_days = (d_to - d_from).days + 1
        run_date = d_to + timedelta(days=1)
    elif d_from or d_to:
        raise click.UsageError("--from กับ --to ต้องใส่คู่กัน")

    shops = cfg.select(shop_id=shop, platform=platform)
    run_id_hint = run_date.isoformat()
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, run_id_hint)

    with StatusStore(PROJECT_ROOT / cfg.settings.paths.db_path) as store:
        stale = store.mark_stale_running()
        if stale:
            click.echo(f"⚠️  เจอแถวค้างสถานะ RUNNING {stale} แถว จากรอบก่อนที่ไม่จบ — ปรับเป็น FAILED แล้ว")
        try:
            with run_lock(PROJECT_ROOT / cfg.settings.paths.lock_file):
                results = Runner(cfg, store).run_many(shops, run_date)
        except AlreadyRunningError as exc:
            click.echo(f"❌ {exc}", err=True)
            sys.exit(2)

    line = summarize(results)
    click.echo(f"\n[{run_date.isoformat()}] {line}")
    click.echo(f"ไฟล์อยู่ที่: output/{run_date.isoformat()}/")
    # exit code != 0 เพื่อให้ Task Scheduler เห็นว่ารอบนี้ไม่สมบูรณ์
    sys.exit(1 if any(r.status.value == "FAILED" for r in results) else 0)


@cli.command()
@click.option("--shop", help="เช็คร้านเดียว (ไม่ใส่ = เช็คทุกร้าน)")
def health(shop: str | None) -> None:
    """เช็คว่า credential ของแต่ละร้านยังใช้ได้ไหม — ไม่ดึงข้อมูลจริง"""
    cfg = load_config()
    shops = cfg.select(shop_id=shop)

    click.echo(f"{'ร้าน':<14} {'แพลตฟอร์ม':<10} {'สถานะ':<8} รายละเอียด")
    click.echo("─" * 88)
    bad = 0
    for s in shops:
        if not s.enabled:
            click.echo(f"{s.shop_id:<14} {s.platform:<10} {'⚪ ข้าม':<8} {s.skip_reason or 'ปิดไว้'}")
            continue
        try:
            with build_adapter(s, cfg.settings) as adapter:
                st = adapter.health_check()
            mark = "🟢 ปกติ" if st.ok else "🔴 มีปัญหา"
            left = f" (เหลือ {st.days_left} วัน)" if st.days_left is not None else ""
            click.echo(f"{s.shop_id:<14} {s.platform:<10} {mark:<8} {st.message}{left}")
            bad += 0 if st.ok else 1
        except Exception as exc:                        # noqa: BLE001
            click.echo(f"{s.shop_id:<14} {s.platform:<10} {'🔴 มีปัญหา':<8} {type(exc).__name__}: {exc}")
            bad += 1

    click.echo(f"\nต้องแก้ {bad} ร้าน จากทั้งหมด {len(shops)} ร้าน")
    sys.exit(1 if bad else 0)


@cli.command()
@click.option("--from", "date_from_s", required=True, help="YYYY-MM-DD")
@click.option("--to", "date_to_s", required=True, help="YYYY-MM-DD")
@click.option("--shop", help="เฉพาะร้านเดียว")
@click.option("--platform", type=click.Choice(["shopee", "lazada", "tiktok"]))
def backfill(date_from_s: str, date_to_s: str, shop: str | None, platform: str | None) -> None:
    """ดึงย้อนหลังทีละวัน (ได้ Excel แยกไฟล์ต่อวัน เหมือนรันจริงในวันนั้น)"""
    cfg = load_config()
    d_from, d_to = _parse(date_from_s, "--from"), _parse(date_to_s, "--to")
    assert d_from and d_to
    if d_from > d_to:
        raise click.BadParameter("--from ต้องไม่หลัง --to")

    shops = cfg.select(shop_id=shop, platform=platform)
    cfg.settings.fetch.lookback_days = 1
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, f"backfill_{d_from}_{d_to}")

    with StatusStore(PROJECT_ROOT / cfg.settings.paths.db_path) as store:
        runner = Runner(cfg, store)
        with run_lock(PROJECT_ROOT / cfg.settings.paths.lock_file):
            day = d_from
            while day <= d_to:
                # run_date = วันถัดไป เพราะ runner ดึง "เมื่อวานของ run_date"
                results = runner.run_many(shops, day + timedelta(days=1))
                click.echo(f"[{day.isoformat()}] {summarize(results)}")
                day += timedelta(days=1)


@cli.command()
@click.option("--shop", required=True, help="ร้านที่จะ login")
def login(shop: str) -> None:
    """เปิดเบราว์เซอร์ให้ล็อกอินเอง แล้วเก็บ cookie ไว้ใช้ซ้ำ (Phase 3)"""
    cfg = load_config()
    s = cfg.shop(shop)

    if s.adapter != "playwright":
        # สร้าง adapter แบบ playwright ชั่วคราวเพื่อ login ได้ แม้ shops.yaml ยังตั้ง mock อยู่
        s = s.model_copy(update={"adapter": "playwright"})

    adapter = build_adapter(s, cfg.settings)
    if not hasattr(adapter, "interactive_login"):
        raise click.ClickException(f"adapter ของ {s.platform} ยังไม่รองรับการล็อกอิน")

    try:
        adapter.interactive_login()
    finally:
        adapter.close()


@cli.command()
def dashboard() -> None:
    """เปิด Streamlit dashboard (Phase 2)"""
    click.echo("❌ Dashboard ยังไม่พร้อมใน Phase 1 — จะทำใน Phase 2")
    click.echo("   เมื่อพร้อมแล้วจะเปิดด้วย: streamlit run src/dashboard/app.py")
    sys.exit(3)


if __name__ == "__main__":
    cli()
