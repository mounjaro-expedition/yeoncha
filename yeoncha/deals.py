"""특가 판정. 세 가지 신호 중 하나라도 걸리면 특가로 본다.
1) 노선 평소가 대비: 같은 노선·같은 박수의 최근 N일 중앙값보다 threshold 이상 저렴
2) 이 날짜 하락: 같은 출국·귀국일의 과거 관측 중앙값보다 trip_drop 이상 하락 (연휴 날짜용)
3) 목표가: 이력이 부족한 초기(콜드스타트)엔 config의 cap 이하면 특가
"""
from dataclasses import dataclass
from datetime import timedelta
from statistics import median


@dataclass
class Deal:
    window: object
    offer: object
    dest_name: str
    discount: float   # 0.3 = 30% 저렴
    reason: str
    is_new: bool = True  # False면 이미 텔레그램으로 보낸 특가 (사이트에는 계속 노출)


def find_deals(store, windows, offers, cfg, today) -> list:
    dc = cfg["deal"]
    since = today - timedelta(days=dc["baseline_days"])
    by_dates = {(w.start.isoformat(), w.end.isoformat()): w for w in windows}

    cheapest = {}
    for o in offers:
        k = (o.origin, o.destination, o.depart, o.ret)
        if (o.depart, o.ret) in by_dates and (k not in cheapest or o.price < cheapest[k].price):
            cheapest[k] = o

    deals = []
    for (orig, dest, dep, ret), offer in cheapest.items():
        w = by_dates[(dep, ret)]
        dinfo = cfg["destinations"].get(dest, {})
        candidates = []  # (discount, reason)

        route = store.route_prices(orig, dest, since, nights=w.nights)
        if len(route) < dc["min_samples"]:
            route = store.route_prices(orig, dest, since)
        if len(route) >= dc["min_samples"]:
            d = 1 - offer.price / median(route)
            if d >= dc["threshold"]:
                candidates.append((d, f"평소보다 {d:.0%}↓"))

        trip = store.trip_prices_before(orig, dest, dep, ret, today)
        if len(trip) >= 3:
            d = 1 - offer.price / median(trip)
            if d >= dc["trip_drop"]:
                candidates.append((d, f"이 날짜 최근가 대비 {d:.0%}↓"))

        cap = dinfo.get("cap")
        if not candidates and len(route) < dc["min_samples"] and cap and offer.price <= cap:
            candidates.append((1 - offer.price / cap, "목표가 이하"))

        if not candidates:
            continue

        last = store.last_alert_price(orig, dest, dep, ret)
        # 이미 보낸 특가는 더 떨어졌을 때만 다시 알림
        is_new = last is None or offer.price <= last * (1 - dc["realert_drop"])

        disc, reason = max(candidates)
        deals.append(Deal(w, offer, dinfo.get("name", dest), disc, reason, is_new))

    # 공휴일 낀 '꿀연휴' 우선, 그다음 할인율 순
    deals.sort(key=lambda x: (not x.window.boosted, -x.discount))
    return deals
