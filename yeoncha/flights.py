"""항공권 가격 수집. 실데이터는 Travelpayouts(Aviasales) Data API, 테스트는 목업."""
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


@dataclass
class Offer:
    origin: str
    destination: str
    depart: str      # YYYY-MM-DD
    ret: str         # YYYY-MM-DD
    price: int       # 왕복 총액 (KRW)
    airline: str
    transfers: int   # 가는 편 + 오는 편 경유 횟수
    link: str        # Aviasales 상대 경로 (/search/...)
    dep_time: str = ""   # 가는 편 출발 시각 HH:MM (출발지 현지)
    ret_time: str = ""   # 오는 편 출발 시각 HH:MM (여행지 현지)
    arr_time: str = ""   # 가는 편 도착 시각 (여행지 현지)
    home_time: str = ""  # 오는 편 도착 시각 (출발지 현지)
    stay_h: float = None # 현지 체류 시간 (도착 ~ 귀국편 출발)


def timing(dep_iso, ret_iso, dur_to=None, dur_back=None) -> dict:
    """출발·귀국 시각(시간대 포함)과 비행시간(분)으로 도착 시각과 현지 체류 시간을 계산."""
    try:
        dep = datetime.fromisoformat(dep_iso.replace("Z", "+00:00"))
        ret = datetime.fromisoformat(ret_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return {}
    out = {"dep_time": dep.strftime("%H:%M"), "ret_time": ret.strftime("%H:%M")}
    if not (dep.tzinfo and ret.tzinfo):
        return out
    if dur_to:
        arr = (dep + timedelta(minutes=int(dur_to))).astimezone(ret.tzinfo)
        out["arr_time"] = ("다음날 " if arr.date() > dep.date() else "") + arr.strftime("%H:%M")
        out["stay_h"] = round((ret - arr).total_seconds() / 3600, 1)
    if dur_back:
        home = (ret + timedelta(minutes=int(dur_back))).astimezone(dep.tzinfo)
        out["home_time"] = ("다음날 " if home.date() > ret.date() else "") + home.strftime("%H:%M")
    return out


def fetch_prices(token, origin, destination, depart_month, return_month, cfg) -> list:
    """출국월·귀국월 조합으로 한 번에 조회 후, 날짜 매칭은 로컬에서 한다 (호출 수 절약).
    주의: Data API는 최근 사용자 검색 기반 '캐시 가격'이라 실시간 가격과 다를 수 있다."""
    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": depart_month,
        "one_way": "false",
        "currency": cfg.get("currency", "krw"),
        "sorting": "price",
        "limit": 1000,
        "page": 1,
        "token": token,
    }
    if return_month:  # 비우면 귀국일 제한 없이 왕복 전체
        params["return_at"] = return_month
    if cfg.get("direct_only", True):
        params["direct"] = "true"
    if cfg.get("market"):
        params["market"] = cfg["market"]
    r = requests.get(API_URL, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    if not js.get("success", False):
        raise RuntimeError(f"API error: {js}")
    out = []
    for it in js.get("data", []):
        if not it.get("return_at"):
            continue
        transfers = int(it.get("transfers", 0)) + int(it.get("return_transfers", 0))
        if cfg.get("direct_only", True) and transfers > 0:
            continue  # 혹시 섞여 들어온 경유편 제거
        out.append(Offer(
            origin=origin,
            destination=destination,
            depart=it["departure_at"][:10],
            ret=it["return_at"][:10],
            price=int(round(float(it["price"]))),
            airline=it.get("airline", ""),
            transfers=transfers,
            link=it.get("link", ""),
            **timing(it["departure_at"], it["return_at"], it.get("duration_to"), it.get("duration_back")),
        ))
    return out


def build_link(link: str, marker: str):
    """제휴 링크 생성. 정식 출시 전 Travelpayouts 대시보드의 링크 생성기로 형식을 꼭 확인하세요."""
    if not link:
        return None
    url = "https://www.aviasales.com" + link
    if marker:
        url += ("&" if "?" in url else "?") + f"marker={marker}"
    return url


# ---------------- 목업 (API 토큰 없이 로직 테스트용) ----------------

# 목업용 노선 정보: (편도 비행시간 분, 현지 시간대)
MOCK_ROUTES = {"OSA": (110, 9), "TYO": (140, 9), "FUK": (80, 9), "SPK": (170, 9), "TPE": (150, 8),
               "HKG": (230, 8), "SHA": (120, 8), "DAD": (290, 7), "BKK": (360, 7), "CEB": (270, 8)}


def mock_offers(windows, cfg, rng) -> list:
    offers = []
    for o in cfg["origins"]:
        for code, d in cfg["destinations"].items():
            dur, tz = MOCK_ROUTES.get(code, (180, 9))
            for w in windows:
                price = int(d["cap"] * rng.uniform(0.72, 1.4) // 100 * 100)
                if rng.random() < 0.25:  # 밤 출발·아침 귀국 패턴 (LCC 최저가에 흔함)
                    dh, rh = rng.choice([21, 22]), rng.choice([6, 7, 8])
                else:
                    dh, rh = rng.choice([7, 8, 9, 10, 13, 15]), rng.choice([11, 14, 17, 19, 20])
                dep_iso = f"{w.start}T{dh:02d}:{rng.choice(['05', '30', '50'])}:00+09:00"
                ret_iso = f"{w.end}T{rh:02d}:{rng.choice(['10', '40'])}:00+{tz:02d}:00"
                offers.append(Offer(o, code, w.start.isoformat(), w.end.isoformat(), price,
                                    rng.choice(["7C", "LJ", "TW", "RS", "UO", "KE", "OZ"]), 0, "",
                                    **timing(dep_iso, ret_iso, dur, dur - 10)))
    return offers


def seed_mock_history(store, cfg, windows, today, rng):
    """최근 40일치 가짜 가격 이력 생성 → '평소 가격' 기준선 테스트."""
    rows = []
    for o in cfg["origins"]:
        for code, d in cfg["destinations"].items():
            cap = d["cap"]
            for back in range(1, 41):
                obs = today - timedelta(days=back)
                for nights in (2, 3, 4):
                    for _ in range(3):
                        dep = today + timedelta(days=rng.randint(10, 200))
                        rows.append(Offer(o, code, dep.isoformat(), (dep + timedelta(nights)).isoformat(),
                                          int(cap * rng.uniform(0.9, 1.3)), "XX", 0, ""))
                store.save_offers(rows, obs)
                rows = []
            # 특정 연휴 날짜의 과거 가격도 일부 생성 (날짜별 하락 감지 테스트)
            for w in windows[::3]:
                for back in (3, 7, 14):
                    store.save_offers([Offer(o, code, w.start.isoformat(), w.end.isoformat(),
                                             int(cap * rng.uniform(1.0, 1.25)), "XX", 0, "")],
                                      today - timedelta(days=back))



class ExactFetcher:
    """출국·귀국일을 지정해 그 날짜의 직항 최저가를 조회. 같은 실행 안에서는 캐시해서 중복 호출을 막는다."""

    def __init__(self, token, cfg, sleep):
        self.token, self.cfg, self.sleep = token, cfg, sleep
        self.cache = {}
        self.calls = 0

    def cheapest(self, origin, dest, depart, ret):
        key = (origin, dest, depart, ret)
        if key not in self.cache:
            best = None
            try:
                res = [f for f in fetch_prices(self.token, origin, dest, depart, ret, self.cfg)
                       if f.depart == depart and f.ret == ret]
                best = min(res, key=lambda f: f.price) if res else None
            except Exception as e:
                print(f"[warn] 날짜 조회 실패 {origin}-{dest} {depart}~{ret}: {e}")
            self.calls += 1
            self.sleep()
            self.cache[key] = best
        return self.cache[key]


def verify_deals(lookup, deals, cfg):
    """특가 후보를 '그 날짜 그대로' 다시 조회해서 아직 그 가격인지 확인.
    가격이 tolerance 이상 올랐거나 사라졌으면 제외, 내려갔으면 새 가격으로 교체."""
    tol = cfg["deal"].get("verify_tolerance", 0.05)
    kept = []
    for d in deals:
        o = d.offer
        best = lookup(o.origin, o.destination, o.depart, o.ret)
        if best is None or best.price > o.price * (1 + tol):
            continue
        d.offer = best
        kept.append(d)
    return kept
