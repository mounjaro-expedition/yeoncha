"""한국 공휴일 기준으로 '연차 0~1일'로 만들 수 있는 연휴 구간을 계산한다."""
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

WEEKDAYS = "월화수목금토일"


def load_holidays(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {date.fromisoformat(h["date"]): h["name"] for h in data["holidays"]}


def composition(depart, ret, holidays) -> tuple:
    """(총 일수, 쉬는 날 수). 쉬는 날 = 주말 + 공휴일. 문자열 날짜도 받는다."""
    if isinstance(depart, str):
        depart, ret = date.fromisoformat(depart), date.fromisoformat(ret)
    days = (ret - depart).days + 1
    off = sum(1 for i in range(days)
              if (depart + timedelta(i)).weekday() >= 5 or (depart + timedelta(i)) in holidays)
    return days, off


def fmt(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


@dataclass(frozen=True)
class Window:
    start: date            # 출국일 = 연휴 첫날
    end: date              # 귀국일 = 연휴 마지막 날
    leave: tuple           # 연차 쓰는 날짜들
    holiday_names: tuple   # 구간에 포함된 공휴일 이름
    weekday_holidays: int = 0  # 평일에 걸린 공휴일 수 (실제로 연휴를 늘려준 날)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def nights(self) -> int:
        return self.days - 1

    @property
    def boosted(self) -> bool:
        """평일 공휴일 덕을 본 '꿀연휴'인지 (주말에 걸린 공휴일은 제외)."""
        return self.weekday_holidays > 0

    def title(self) -> str:
        n = len(self.leave)
        head = f"연차 {n}일로" if n else "연차 없이"
        return f"{head} {self.nights}박{self.days}일"

    def describe(self) -> str:
        leave = ", ".join(fmt(d) for d in self.leave) or "없음"
        hol = " · ".join(self.holiday_names)
        return f"{fmt(self.start)} → {fmt(self.end)} | 연차: {leave}" + (f" | {hol}" if hol else "")


def find_windows(holidays: dict, start: date, end: date, min_days: int = 3) -> list:
    """출국일이 [start, end] 안에 있는, 연차 0~1일로 가능한 min_days 이상 연휴 목록."""

    def off(d, extra=None):
        return d.weekday() >= 5 or d in holidays or d == extra

    def block(d, extra=None):
        s = e = d
        while off(s - timedelta(1), extra):
            s -= timedelta(1)
        while off(e + timedelta(1), extra):
            e += timedelta(1)
        return s, e

    found = {}  # (s, e) -> leave tuple (연차 적은 쪽 우선)
    d = start - timedelta(days=10)
    while d <= end + timedelta(days=10):
        if off(d):
            s, e = block(d)
            leave = ()
        else:
            s, e = block(d, extra=d)
            leave = (d,)
        key = (s, e)
        if key not in found or len(leave) < len(found[key]):
            found[key] = leave
        d += timedelta(1)

    windows = []
    for (s, e), leave in found.items():
        if (e - s).days + 1 < min_days or not (start <= s <= end):
            continue
        names, wk = [], 0
        cur = s
        while cur <= e:
            if cur in holidays:
                if holidays[cur] not in names:
                    names.append(holidays[cur])
                if cur.weekday() < 5:
                    wk += 1
            cur += timedelta(1)
        windows.append(Window(s, e, leave, tuple(names), wk))
    return sorted(windows, key=lambda w: (w.start, w.end))
