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
            for _ in range(70 * (end - start).days // 90):  # 기간에 비례
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
        "hotel": hotel_link(cfg, o.destination, o.depart, o.ret) if n > 0 else "",
        **bag_info(o.airline, airlines, o.destination),
    }


CITY_EN = {"FUK": "Fukuoka", "OSA": "Osaka", "TYO": "Tokyo", "NGO": "Nagoya", "SPK": "Sapporo",
           "OKA": "Naha", "KKJ": "Kitakyushu", "OIT": "Oita", "KMJ": "Kumamoto", "KOJ": "Kagoshima",
           "NGS": "Nagasaki", "HSG": "Saga", "HIJ": "Hiroshima", "OKJ": "Okayama", "TAK": "Takamatsu",
           "MYJ": "Matsuyama", "YGJ": "Yonago", "UBJ": "Ube", "KMQ": "Komatsu", "FSZ": "Shizuoka",
           "TOY": "Toyama", "SDJ": "Sendai", "KIJ": "Niigata", "IBR": "Mito", "AOJ": "Aomori"}


def hotel_link(cfg, dest, checkin, checkout):
    tpl = cfg.get("site", {}).get("hotel_url", "")
    if not tpl:
        return ""
    from urllib.parse import quote
    return (tpl.replace("{city_en}", quote(CITY_EN.get(dest, dest)))
               .replace("{city_ko}", quote(cfg["destinations"].get(dest, dest)))
               .replace("{checkin}", checkin).replace("{checkout}", checkout))


def slim(x):
    """사이트용 짧은 형식 (이름·날짜 표기는 페이지에서 계산해서 용량 절약)."""
    return [x["from"], x["to"], x["dep"], x["nights"], x["leave"], x["price"],
            x["depTime"], x["arrTime"], x["retTime"], x["homeTime"], x["stayH"],
            x["link"], x["bag"], x["addon"], x["airline"], x["hotel"]]


def build_site(items, cfg, today, mock, out, holidays):
    site = cfg.get("site", {})
    data = {"updated": f"{today.month}월 {today.day}일 오전 9시", "mock": mock,
            "telegram": site.get("telegram_url", ""), "esim": site.get("esim_url", ""),
            "origins": cfg["origins"], "dests": cfg["destinations"],
            "rows": [slim(x) for x in items[: site.get("max_items", 12000)]],
            "today": today.isoformat(),
            "holidays": sorted(d.isoformat() for d in holidays if d >= today)}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload).replace("__SITE_URL__", site.get("url", ""))
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    return out / "index.html"


def _bag_short(x):
    if x["bag"] == "included":
        return "수하물 포함"
    if x["bag"] == "lcc":
        return f"수하물 별도(+{x['addon'] // 10000}만원)" if x["addon"] else "수하물 별도"
    return "수하물 확인 필요"


def _pick_diverse(rows, k):
    """싼 순서로 고르되 같은 도착 도시는 한 번만 (일정이 다양하게 보이도록)."""
    out, seen = [], set()
    for x in rows:
        if x["to"] in seen:
            continue
        seen.add(x["to"])
        out.append(x)
        if len(out) == k:
            break
    return out


def build_digest(items, cfg, today, mock):
    groups = [("☀️ 당일치기", lambda x: x["nights"] == 0),
              ("🌙 1~2박", lambda x: 1 <= x["nights"] <= 2),
              ("🧳 3~5박", lambda x: x["nights"] >= 3)]
    k = cfg.get("telegram", {}).get("top_per_group", 5)
    nums = "①②③④⑤⑥⑦⑧⑨⑩"
    test = "[테스트 데이터] " if mock else ""
    lines = [f"🇯🇵 {test}<b>비만주사 원정대</b>  {today.month}/{today.day} 일본 왕복 최저가",
             "<i>같은 도시는 가장 싼 일정 하나만 보여드려요</i>"]
    for title, cond in groups:
        g = _pick_diverse([x for x in items if cond(x)], k)
        if not g:
            continue
        lines.append(f"\n<b>{title}</b>")
        for n, x in enumerate(g):
            head = f"{nums[n]} <b>{x['price']:,}원</b>  {escape(x['fromName'])} → {escape(x['toName'])}"
            if x["link"]:
                head += f'  <a href="{escape(x["link"])}">예약</a>'
            when = x["range"] if x["nights"] == 0 else f"{x['range']} {x['len']}"
            go = f"{x['depTime']}→{x['arrTime'].replace('다음날 ', '+1 ')}" if x["arrTime"] else x["depTime"]
            back = f"{x['retTime']}→{x['homeTime'].replace('다음날 ', '+1 ')}" if x["homeTime"] else x["retTime"]
            info = [escape(x["airline"]), _bag_short(x)]
            if x["nights"] == 0 and x["stayH"] is not None:
                info.append(f"현지 {x['stayH']}시간")
            if x["leave"] == 0:
                info.append("연차 없이")
            lines += [head, f"    {when}", f"    가는 {go}  /  오는 {back}", f"    {' · '.join(info)}"]
    site = cfg.get("site", {}).get("url")
    lines.append(f"\n📅 전체 {len(items):,}건, 날짜별 달력·숙소는 "
                 + (f'<a href="{escape(site)}">사이트에서</a>' if site else "사이트에서"))
    lines.append("<i>※ 오늘 아침 기준 직항 왕복 최저가이며 변동될 수 있어요. 반입 기준은 관세청(125) 확인.\n"
                 "※ 링크로 예약하면 운영자가 소정의 수수료를 받을 수 있어요.</i>")
    return "\n".join(lines)


def build_stats(raw, items, cfg, today, out):
    """데이터 현황 페이지 (검색 노출 안 함). 노선별 수집량과 최저가를 표로."""
    from collections import Counter, defaultdict
    def table(title, head, rows):
        h = "".join(f"<th>{c}</th>" for c in head)
        b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f"<h2>{title}</h2><table><tr>{h}</tr>{b}</table>"
    def agg(key):
        cnt, low = Counter(), {}
        for x in items:
            k = key(x)
            cnt[k] += 1
            low[k] = min(low.get(k, 10**9), x["price"])
        return cnt, low
    O, D = cfg["origins"], cfg["destinations"]
    raw_by_route = Counter((o.origin, o.destination) for o in raw)
    parts = [f"<h1>원정대 데이터 현황 {today}</h1>",
             f"<p>수집 원본 {len(raw):,}건 / 조건 통과 {len(items):,}건 / "
             f"기간 {cfg['lead_days']}~{cfg['horizon_days']}일 / return_month_pairs={cfg.get('return_month_pairs')}</p>"]
    c, l = agg(lambda x: x["from"])
    parts.append(table("출발 공항별", ["공항", "건수", "최저가"], [(O.get(k, k), c[k], f"{l[k]:,}") for k in O if k in c]
                       + [(O.get(k, k), 0, "-") for k in O if k not in c]))
    c, l = agg(lambda x: x["to"])
    parts.append(table("도착 도시별", ["도시", "건수", "최저가"], sorted(
        [(D.get(k, k), c[k], f"{l[k]:,}") for k in D if k in c], key=lambda r: -r[1])
        + [(D.get(k, k), 0, "-") for k in D if k not in c]))
    c, l = agg(lambda x: x["nights"])
    parts.append(table("일정 길이별", ["일정", "건수", "최저가"],
                       [("당일치기" if n == 0 else f"{n}박", c[n], f"{l[n]:,}") for n in sorted(c)]))
    c, l = agg(lambda x: x["dep"][:7])
    parts.append(table("출발 월별", ["월", "건수", "최저가"], [(k, c[k], f"{l[k]:,}") for k in sorted(c)]))
    c, l = agg(lambda x: (x["from"], x["to"]))
    parts.append(table("노선별 (조건 통과 / 수집 원본 / 최저가)", ["노선", "통과", "원본", "최저가"], sorted(
        [(f"{O.get(a, a)}→{D.get(b, b)}", c[(a, b)], raw_by_route[(a, b)], f"{l[(a, b)]:,}") for a, b in c],
        key=lambda r: -r[1])))
    empty = [f"{O.get(a, a)}→{D.get(b, b)}" for a, b in raw_by_route if (a, b) not in c]
    if empty:
        parts.append(f"<h2>원본은 있는데 조건 통과 0건</h2><p>{', '.join(empty)}</p>")
    css = ("body{font:14px/1.5 sans-serif;margin:20px;max-width:900px}table{border-collapse:collapse;margin-bottom:16px}"
           "td,th{border:1px solid #ccc;padding:4px 8px;text-align:right}td:first-child,th:first-child{text-align:left}")
    html = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="robots" content="noindex">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>데이터 현황</title>'
            f'<style>{css}</style></head><body>{"".join(parts)}</body></html>')
    (out / "stats.html").write_text(html, encoding="utf-8")


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
    build_stats(raw, items, cfg, today, ROOT / "docs" / "japan")

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
