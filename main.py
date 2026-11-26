"""연차하루면 충분행 MVP

사용법:
  python main.py windows                 # 연차 1일 연휴 목록 출력
  python main.py run --mock --dry-run    # 토큰 없이 목업 데이터로 전체 흐름 테스트
  python main.py run                     # 실제 수집 + 텔레그램 발송 (환경변수 필요)

환경변수: TP_TOKEN, TP_MARKER, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import argparse
import os
import random
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import yaml

from yeoncha import flights, notify, site
from yeoncha.airlines import load_airlines
from yeoncha.calendar_kr import find_windows, load_holidays
from yeoncha.deals import find_deals
from yeoncha.store import Store

ROOT = Path(__file__).parent


def load_config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def get_windows(cfg, today):
    hol = load_holidays(ROOT / "data" / "holidays_kr.json")
    ws = find_windows(hol, today + timedelta(cfg["lead_days"]),
                      today + timedelta(cfg["horizon_days"]), cfg["min_trip_days"])
    if not cfg.get("include_plain_weekends", True):
        ws = [w for w in ws if w.boosted]
    return ws


def cmd_windows(args):
    cfg = load_config()
    ws = get_windows(cfg, args.today)
    if args.boosted:
        ws = [w for w in ws if w.boosted]
    for w in ws:
        mark = "⭐" if w.boosted else "  "
        print(f"{mark} {w.title():<16} {w.describe()}")
    print(f"\n총 {len(ws)}개 구간 (⭐ = 공휴일 낀 꿀연휴)")


def collect_real(cfg, windows):
    token = os.environ.get("TP_TOKEN")
    if not token:
        sys.exit("TP_TOKEN 환경변수가 없어요. 목업 테스트는 --mock 옵션을 쓰세요.")
    pairs = sorted({(w.start.strftime("%Y-%m"), w.end.strftime("%Y-%m")) for w in windows})
    offers = []
    for o in cfg["origins"]:
        for d in cfg["destinations"]:
            for dm, rm in pairs:
                try:
                    offers += flights.fetch_prices(token, o, d, dm, rm, cfg)
                except Exception as e:  # 한 노선 실패가 전체를 멈추지 않게
                    print(f"[warn] {o}-{d} {dm}/{rm}: {e}", file=sys.stderr)
                time.sleep(cfg.get("request_interval_sec", 0.5))
    return offers


def cmd_run(args):
    cfg = load_config()
    today = args.today
    windows = get_windows(cfg, today)
    store = Store(ROOT / "data" / ("mock.db" if args.mock else "prices.db"))

    if args.mock:
        rng = random.Random(args.seed)
        if store.is_empty():
            flights.seed_mock_history(store, cfg, windows, today, rng)
        offers = flights.mock_offers(windows, cfg, rng)
    else:
        offers = collect_real(cfg, windows)

    print(f"연휴 구간 {len(windows)}개 / 수집 가격 {len(offers)}건")
    deals = find_deals(store, windows, offers, cfg, today)  # 오늘 저장 전에 판정 (오늘 값이 기준선 오염 X)
    store.save_offers(offers, today)
    deals = deals[: cfg["site"]["max_deals"]]

    # 날짜 지정 조회 함수: 실데이터는 API 재조회(캐시), 목업은 수집분에서 찾기
    if args.mock:
        idx = {}
        for o in offers:
            k = (o.origin, o.destination, o.depart, o.ret)
            if k not in idx or o.price < idx[k].price:
                idx[k] = o
        lookup = lambda o, d, dep, ret: idx.get((o, d, dep, ret))
    else:
        fetcher = flights.ExactFetcher(os.environ["TP_TOKEN"], cfg,
                                       lambda: time.sleep(cfg.get("request_interval_sec", 0.5)))
        lookup = fetcher.cheapest

    # 연차 하루 연휴별 주요 여행지 오늘의 최저가
    lw = [w for w in windows if w.boosted and len(w.leave) == 1][: cfg["lowest"]["max_windows"]]
    lowest = {}
    for w in lw:
        found = [lookup(o, d, w.start.isoformat(), w.end.isoformat())
                 for o in cfg["origins"] for d in cfg["destinations"]]
        lowest[w] = sorted([f for f in found if f], key=lambda f: f.price)
    print(f"연휴별 최저가: {len(lw)}개 연휴, {sum(len(v) for v in lowest.values())}건")

    if not args.mock:
        before = len(deals)
        deals = flights.verify_deals(lookup, deals, cfg)
        print(f"재확인: 후보 {before}건 중 {len(deals)}건이 아직 유효 (API 호출 {fetcher.calls}회)")
    marker = os.environ.get("TP_MARKER", "")
    airlines = load_airlines(ROOT / "data" / "airlines.json", mock=args.mock)

    # 사이트: 오늘 유효한 특가 전체 / 텔레그램: 아직 안 보낸 새 특가만
    page = site.build_site(deals, windows, lowest,
                           load_holidays(ROOT / "data" / "holidays_kr.json"),
                           airlines, cfg, marker, today, ROOT / "docs", mock=args.mock)
    new_deals = [d for d in deals if d.is_new][: cfg["max_alerts_per_run"]]
    print(f"특가 {len(deals)}건 (새 특가 {len(new_deals)}건)")
    print(f"웹페이지 생성: {page}\n")

    msgs = notify.build_messages(new_deals, marker, today, airlines, cfg, mock=args.mock)
    bot, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if args.dry_run or not (bot and chat):
        print("── 텔레그램 미리보기 (실제로는 굵은 글씨·링크로 표시) ──\n")
        for m in msgs:
            print(re.sub(r"<[^>]+>", "", m))
        if not args.dry_run:
            print("\n[info] 텔레그램 환경변수가 없어 출력만 했어요.")
        return
    for m in msgs:
        notify.send_telegram(bot, chat, m)
    for d in new_deals:
        store.record_alert(d.offer, today)
    print(f"텔레그램 발송 완료: {len(msgs)}개 메시지")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--today", type=date.fromisoformat, default=date.today(),
                   help="테스트용 기준일 (YYYY-MM-DD)")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("windows")
    w.add_argument("--boosted", action="store_true", help="공휴일 낀 구간만")
    r = sub.add_parser("run")
    r.add_argument("--mock", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    {"windows": cmd_windows, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
