"""비만주사 원정대: 일본 어디든 왕복 직항 최저가 (당일치기 ~ 5박6일), 싼 순서

사용법:
  python japan.py --mock --dry-run   # 토큰 없이 가짜 가격으로 화면 확인
  python japan.py                    # 실제 수집 + 사이트 생성 + 텔레그램 발송

환경변수: TP_TOKEN, TP_MARKER, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID_JAPAN
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date, timedelta
from html import escape
from pathlib import Path

import yaml

from yeoncha import flights, notify
from yeoncha.airlines import bag_info, load_airlines
from yeoncha.calendar_kr import WEEKDAYS, composition, fmt, load_holidays

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "yeoncha" / "japan_template.html"


def month_list(start, end):
    out, d = [], start.replace(day=1)
    while d <= end:
        out.append(d.strftime("%Y-%m"))
        d = (d + timedelta(days=32)).replace(day=1)
    return out


def next_month(ym):
    y, m = map(int, ym.split("-"))
    return f"{y + (m == 12)}-{m % 12 + 1:02d}"


def collect_real(cfg, start, end):
    token = os.environ.get("TP_TOKEN")
    if not token:
        sys.exit("TP_TOKEN 환경변수가 없어요. 화면 테스트는 --mock 옵션을 쓰세요.")
    offers, no_return = [], 0
    for o in cfg["origins"]:
        for d in cfg["destinations"]:
            for m in month_list(start, end):
                pairs = [(m, m), (m, next_month(m))] if cfg.get("return_month_pairs") else [(m, None)]
                for dm, rm in pairs:
                    try:
                        got = flights.fetch_prices(token, o, d, dm, rm, cfg)
                        offers += got
                    except Exception as e:
                        print(f"[warn] {o}-{d} {dm}: {e}", file=sys.stderr)
                    time.sleep(cfg.get("request_interval_sec", 0.3))
    if not offers:
        print("[warn] 왕복 결과가 0건이에요. config_japan.yaml에서 return_month_pairs: true로 바꿔 보세요.")
    return offers


def mock_offers(cfg, start, end, rng):
    """노선별 대략적인 비행시간으로 그럴듯한 가짜 왕복 생성."""
    dur = {"FUK": 80, "KKJ": 85, "OIT": 90, "KMJ": 95, "NGS": 90, "HSG": 85, "KOJ": 105, "HIJ": 95,
           "OKJ": 100, "TAK": 105, "MYJ": 100, "YGJ": 100, "UBJ": 85, "OSA": 110, "KMQ": 120,
           "NGO": 125, "FSZ": 130, "TOY": 120, "TYO": 140, "IBR": 145, "SDJ": 150, "KIJ": 135,
           "AOJ": 160, "SPK": 170, "OKA": 150}
    base = {"FUK": 110000, "OSA": 150000, "TYO": 190000, "OKA": 210000, "SPK": 240000}
    routes = {"ICN": list(cfg["destinations"]), "GMP": ["OSA", "TYO"],
              "PUS": ["FUK", "OSA", "TYO", "NGO", "SPK", "OKA", "KKJ", "KMJ"],
              "CJJ": ["OSA", "FUK", "TYO", "OKA", "SPK"], "TAE": ["OSA", "FUK", "TYO", "OKA"]}
    offers = []
    for o, dests in routes.items():
        for d in dests:
            for _ in range(70):
                dep = start + timedelta(days=rng.randint(0, (end - start).days))
                n = rng.choice([0, 0, 1, 1, 2, 2, 3, 4, 5])
                ret = dep + timedelta(n)
                p = int(base.get(d, 170000) * rng.uniform(0.45, 1.5) * (0.8 if n == 0 else 1) // 100 * 100)
                dh = rng.choice([6, 7, 8, 9, 10, 13])
                rh = rng.choice([15, 17, 18, 19, 20, 21]) if n == 0 else rng.choice([9, 12, 15, 18, 20])
                t = flights.timing(f"{dep}T{dh:02d}:{rng.choice(['05', '35'])}:00+09:00",
                                   f"{ret}T{rh:02d}:{rng.choice(['10', '45'])}:00+09:00",
                                   dur.get(d, 120), dur.get(d, 120) - 5)
                offers.append(flights.Offer(o, d, dep.isoformat(), ret.isoformat(), p,
                                            rng.choice(["7C", "TW", "LJ", "RS", "BX", "ZE", "KE", "OZ"]),
                                            0, "", **t))
    return offers


def select(offers, cfg, start, end):
    """조건(기간·박수·체류시간)에 맞는 것만, 같은 일정은 최저가 하나로."""
    best = {}
    for o in offers:
        dep, ret = date.fromisoformat(o.depart), date.fromisoformat(o.ret)
        n = (ret - dep).days
        if not (start <= dep <= end and cfg["min_nights"] <= n <= cfg["max_nights"]):
            continue
        if o.stay_h is not None and o.stay_h < cfg["min_stay_hours"]:
            continue
        k = (o.origin, o.destination, o.depart, o.ret)
        if k not in best or o.price < best[k].price:
            best[k] = o
    # 달력이 비지 않도록 (출발공항, 출발일, 박수)마다 싼 것 상위 N개는 남긴다
    groups = {}
    for o in sorted(best.values(), key=lambda o: o.price):
        g = groups.setdefault((o.origin, o.depart, o.ret), [])
        if len(g) < cfg.get("per_day_keep", 3):
            g.append(o)
    return sorted((o for g in groups.values() for o in g), key=lambda o: o.price)


def to_json(o, cfg, holidays, airlines, marker):
    dep, ret = date.fromisoformat(o.depart), date.fromisoformat(o.ret)
    n = (ret - dep).days
    days, off = composition(dep, ret, holidays)
    return {
        "from": o.origin, "fromName": cfg["origins"].get(o.origin, o.origin),
        "to": o.destination, "toName": cfg["destinations"].get(o.destination, o.destination),
        "dep": o.depart, "ret": o.ret, "nights": n,
        "len": "당일치기" if n == 0 else f"{n}박{n + 1}일",
        "range": fmt(dep) if n == 0 else f"{fmt(dep)} ~ {fmt(ret)}",
        "leave": days - off, "holiday": any(dep + timedelta(i) in holidays for i in range(days)),
        "price": o.price, "depTime": o.dep_time, "arrTime": o.arr_time,
        "retTime": o.ret_time, "homeTime": o.home_time,
        "stayH": round(o.stay_h) if o.stay_h is not None else None,
        "link": flights.build_link(o.link, marker) or "",
        **bag_info(o.airline, airlines, o.destination),
    }


def build_site(items, cfg, today, mock, out, holidays):
    site = cfg.get("site", {})
    data = {"updated": f"{today.month}월 {today.day}일 오전 9시", "mock": mock,
            "telegram": site.get("telegram_url", ""), "esim": site.get("esim_url", ""),
            "origins": cfg["origins"], "items": items[: site.get("max_items", 5000)],
            "today": today.isoformat(),
            "holidays": sorted(d.isoformat() for d in holidays if d >= today)}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload).replace("__SITE_URL__", site.get("url", ""))
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    return out / "index.html"


def build_digest(items, cfg, today, mock):
    groups = [("☀️ 당일치기", lambda x: x["nights"] == 0),
              ("🌙 1~2박", lambda x: 1 <= x["nights"] <= 2),
              ("🧳 3~5박", lambda x: x["nights"] >= 3)]
    k = cfg.get("telegram", {}).get("top_per_group", 3)
    test = "[테스트 데이터] " if mock else ""
    lines = [f"🇯🇵 {test}<b>비만주사 원정대</b> {today:%m/%d} 일본 왕복 최저가"]
    for title, cond in groups:
        g = [x for x in items if cond(x)][:k]
        if not g:
            continue
        lines.append(f"\n<b>{title}</b>")
        for x in g:
            stay = f", 현지 {x['stayH']}시간" if x["stayH"] is not None else ""
            leave = "연차 0일" if x["leave"] == 0 else f"연차 {x['leave']}일"
            row = (f"<b>{x['price']:,}원</b> {escape(x['fromName'])}→{escape(x['toName'])} "
                   f"{x['range']} {x['len']}{stay}, {leave}\n   {escape(x['airline'])}, "
                   f"{x['depTime']} 출발 / 귀국편 {x['retTime']}")
            if x["link"]:
                row += f' <a href="{escape(x["link"])}">예약</a>'
            lines.append(row)
    site = cfg.get("site", {}).get("url")
    if site:
        lines.append(f'\n📅 날짜별 최저가 달력: <a href="{escape(site)}">사이트에서 보기</a>')
    lines.append("\n<i>※ 오늘 아침 기준 직항 왕복 최저가(수하물 별도일 수 있음)이며 변동될 수 있어요."
                 "\n※ 의약품 반입 기준은 관세청(125)에서 꼭 확인하세요."
                 "\n※ 링크를 통해 예약하면 운영자가 소정의 수수료를 받을 수 있어요.</i>")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    p.add_argument("--mock", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    cfg = yaml.safe_load((ROOT / "config_japan.yaml").read_text(encoding="utf-8"))
    today = args.today
    start, end = today + timedelta(cfg["lead_days"]), today + timedelta(cfg["horizon_days"])
    holidays = load_holidays(ROOT / "data" / "holidays_kr.json")
    airlines = load_airlines(ROOT / "data" / "airlines.json")
    marker = os.environ.get("TP_MARKER", "")

    raw = mock_offers(cfg, start, end, random.Random(args.seed)) if args.mock else collect_real(cfg, start, end)
    picked = select(raw, cfg, start, end)
    items = [to_json(o, cfg, holidays, airlines, marker) for o in picked]
    print(f"[원정대] 수집 {len(raw)}건 → 조건 통과 {len(items)}건 (당일치기 {sum(i['nights'] == 0 for i in items)}건)")
    page = build_site(items, cfg, today, args.mock, ROOT / "docs" / "japan", holidays)
    print(f"[원정대] 웹페이지 생성: {page}")

    if not items:
        return
    msg = build_digest(items, cfg, today, args.mock)
    bot, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID_JAPAN")
    if args.dry_run or not (bot and chat):
        print("\n── 텔레그램 미리보기 ──\n")
        print(re.sub(r"<[^>]+>", "", msg))
        return
    notify.send_telegram(bot, chat, msg)
    print("[원정대] 텔레그램 발송 완료")


if __name__ == "__main__":
    main()
