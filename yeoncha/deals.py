"""특가 판정. '일정 길이 + 쉬는 날 수'가 같은 일정끼리만 비교한다.
(예: 휴일 3일·평일 2일인 5일 일정은 다른 '휴일 3·평일 2' 5일 일정과 비교. 요일 배치는 달라도 됨)

신호 (하나라도 걸리면 특가):
1) 평소 대비: 같은 노선·같은 구성 일정의 최근 N일 관측 중앙값보다 threshold 이상 저렴
2) 오늘 시장 대비: 기록이 부족한 초기엔, 오늘 수집한 같은 노선·같은 구성 '다른 날짜'들의 중앙값과 비교
3) 이 날짜 하락: 같은 출국·귀국일의 과거 관측 중앙값보다 trip_drop 이상 하락
4) 목표가: 1·2 모두 표본이 없을 때만 config의 cap 이하면 특가
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from statistics import median

from .calendar_kr import composition


@dataclass
class Deal:
    window: object
    offer: object
    dest_name: str
    discount: float   # 0.3 = 30% 저렴
    reason: str
    is_new: bool = True  # False면 이미 텔레그램으로 보낸 특가 (사이트에는 계속 노출)


def _label(comp):
    """여행 일정 속 평일 = 연차 써야 하는 날."""
    days, off = comp
    work = days - off
    return f"휴일 {off}일+연차 {work}일 일정" if work else f"휴일 {off}일 일정"


def find_deals(store, windows, offers, cfg, today, holidays) -> list:
    dc = cfg["deal"]
    since = today - timedelta(days=dc["baseline_days"])
    by_dates = {(w.start.isoformat(), w.end.isoformat()): w for w in windows}

    # 날짜쌍별 최저가 (같은 날짜에 여러 항공사가 있으면 가장 싼 것)
    best = {}
    for o in offers:
        k = (o.origin, o.destination, o.depart, o.ret)
        if k not in best or o.price < best[k].price:
            best[k] = o

    # 오늘 시장: 노선·구성별 가격 목록
    market = defaultdict(list)
    for (orig, dest, dep, ret), o in best.items():
        market[(orig, dest, composition(dep, ret, holidays))].append(((dep, ret), o.price))

    history_cache = {}
    deals = []
    for (orig, dest, dep, ret), offer in best.items():
        if (dep, ret) not in by_dates:
            continue
        w = by_dates[(dep, ret)]
        comp = composition(dep, ret, holidays)
        dinfo = cfg["destinations"].get(dest, {})
        candidates = []

        if (orig, dest) not in history_cache:
            history_cache[(orig, dest)] = store.route_rows(orig, dest, since)
        hist = [p for d0, r0, p in history_cache[(orig, dest)]
                if composition(d0, r0, holidays) == comp]
        if len(hist) >= dc["min_samples"]:
            d = 1 - offer.price / median(hist)
            if d >= dc["threshold"]:
                candidates.append((d, f"{_label(comp)} 평소보다 {d:.0%}↓"))
        else:
            others = [p for dates, p in market[(orig, dest, comp)] if dates != (dep, ret)]
            if len(others) >= dc.get("market_min_samples", 4):
                d = 1 - offer.price / median(others)
                if d >= dc["threshold"]:
                    candidates.append((d, f"{_label(comp)} 중 {d:.0%} 저렴"))
            else:
                cap = dinfo.get("cap")
                if cap and offer.price <= cap:
                    candidates.append((1 - offer.price / cap, "목표가 이하"))

        trip = store.trip_prices_before(orig, dest, dep, ret, today)
        if len(trip) >= 3:
            d = 1 - offer.price / median(trip)
            if d >= dc["trip_drop"]:
                candidates.append((d, f"이 날짜 최근가 대비 {d:.0%}↓"))

        if not candidates:
            continue

        last = store.last_alert_price(orig, dest, dep, ret)
        is_new = last is None or offer.price <= last * (1 - dc["realert_drop"])
        disc, reason = max(candidates)
        deals.append(Deal(w, offer, dinfo.get("name", dest), disc, reason, is_new))

    # 공휴일 낀 '꿀연휴' 우선, 그다음 할인율 순
    deals.sort(key=lambda x: (not x.window.boosted, -x.discount))
    return deals
