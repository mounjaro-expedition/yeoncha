"""현지 체류 시간으로 '알찬 일정'과 '밤도깨비'(밤 도착·새벽 귀국 등 짧은 일정)를 나눈다."""


def _hour(t):
    return int(t.replace("다음날 ", "")[:2])


def classify(offer, window, cfg) -> dict:
    # 귀국편이 날짜를 넘겨 도착하면 연휴 다음 날(보통 출근일) 새벽 도착
    late = offer.home_time.startswith("다음날")
    warn = "연휴 다음 날 새벽 도착이라 출근 전 쉴 시간이 거의 없어요" if late else ""
    if offer.stay_h is None:
        return {"stayH": None, "night": False, "nightWhy": "", "warn": warn}
    limit = window.nights * 24 * cfg.get("stay", {}).get("short_ratio", 0.65)
    night = offer.stay_h < limit
    why = []
    if night:
        if offer.arr_time and (_hour(offer.arr_time) >= 21 or _hour(offer.arr_time) < 5):
            why.append("밤 도착")
        if offer.ret_time and _hour(offer.ret_time) < 10:
            why.append("아침 일찍 귀국")
        if not why:
            why.append("현지 체류가 짧아요")
    return {"stayH": round(offer.stay_h), "night": night, "nightWhy": ", ".join(why), "warn": warn}
