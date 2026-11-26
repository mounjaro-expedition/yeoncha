"""특가 목록을 정적 웹페이지(docs/index.html)로 생성. GitHub Pages로 무료 호스팅."""
import json
from datetime import timedelta
from pathlib import Path

from .airlines import bag_info
from .calendar_kr import WEEKDAYS, fmt
from .flights import build_link
from .stay import classify

TEMPLATE = Path(__file__).parent / "site_template.html"


def _strip(window, holidays):
    """여행 기간의 하루하루를 달력 칸으로 변환."""
    cells, d = [], window.start
    while d <= window.end:
        if d in window.leave:
            kind = "leave"
        elif d in holidays or d.weekday() == 6:
            kind = "red"
        elif d.weekday() == 5:
            kind = "sat"
        else:
            kind = "work"
        cells.append({"m": d.month, "d": d.day, "wd": WEEKDAYS[d.weekday()],
                      "kind": kind, "name": holidays.get(d, "")})
        d += timedelta(1)
    return cells


def _window_json(w, holidays):
    return {
        "id": f"{w.start:%Y%m%d}-{w.end:%Y%m%d}",
        "title": w.title(),
        "range": f"{fmt(w.start)} ~ {fmt(w.end)}",
        "month": f"{w.start.year}-{w.start.month:02d}",
        "monthLabel": f"{w.start.month}월",
        "leave": [fmt(x) for x in w.leave],
        "holidays": list(w.holiday_names),
        "boosted": w.boosted,
        "days": w.days,
        "strip": _strip(w, holidays),
    }


def _offer_json(o, w, cfg, airlines, marker):
    return {
        "city": cfg["destinations"].get(o.destination, {}).get("name", o.destination),
        "price": o.price,
        "depTime": o.dep_time,
        "retTime": o.ret_time,
        "arrTime": o.arr_time,
        "homeTime": o.home_time,
        **classify(o, w, cfg),
        "link": build_link(o.link, marker) or "",
        **bag_info(o.airline, airlines, o.destination),
    }


def build_site(deals, windows, lowest, holidays, airlines, cfg, marker, now, out_dir, mock=False):
    site = cfg.get("site", {})
    deal_keys = {(d.offer.destination, d.window.start, d.window.end) for d in deals}
    win_list = []
    for w in windows:
        if not (w.boosted and len(w.leave) == 1):
            continue
        wj = _window_json(w, holidays)
        wj["lowest"] = [
            {**_offer_json(o, w, cfg, airlines, marker),
             "deal": (o.destination, w.start, w.end) in deal_keys}
            for o in lowest.get(w, [])
        ]
        wj["checked"] = w in lowest
        win_list.append(wj)

    data = {
        "updated": f"{now.month}월 {now.day}일 오전 9시",
        "mock": mock,
        "telegram": site.get("telegram_url", ""),
        "deals": [
            {**_window_json(d.window, holidays),
             **_offer_json(d.offer, d.window, cfg, airlines, marker),
             "city": d.dest_name, "reason": d.reason, "discount": round(d.discount, 3)}
            for d in deals
        ],
        "windows": win_list,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", payload)
            .replace("__SITE_URL__", site.get("url", "")))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    return out / "index.html"
