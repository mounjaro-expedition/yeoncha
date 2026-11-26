"""텔레그램 채널로 하루 1회 다이제스트 발송."""
from html import escape

import requests

from .calendar_kr import fmt
from .airlines import bag_info
from .flights import build_link
from .stay import classify

FOOTER = ("\n<i>※ 오늘 아침 재확인한 가격이며 실제 예약 시 달라질 수 있어요.\n"
          "※ 링크를 통해 예약하면 운영자가 소정의 수수료를 받을 수 있어요.</i>")


def format_deal(deal, marker, airlines, cfg) -> str:
    w, o = deal.window, deal.offer
    st = classify(o, w, cfg)
    go = f"가는 편 {o.dep_time} 출발" + (f"({o.arr_time} 도착)" if o.arr_time else "")
    back = f"오는 편 {o.ret_time} 출발" + (f"({o.home_time} 도착)" if o.home_time else "")
    times = f"{go} / {back}" if o.dep_time else "직항"
    lines = [
        f"✈️ <b>{escape(deal.dest_name)}</b> · {w.title()}",
        f"🗓 {fmt(w.start)} → {fmt(w.end)}",
        "🏖 연차 " + (", ".join(fmt(d) for d in w.leave) or "없음")
        + (f" | {escape(' · '.join(w.holiday_names))}" if w.holiday_names else ""),
        f"💰 <b>{o.price:,}원</b> 직항 왕복 ({deal.reason})",
        f"🕘 {times}",
        *([f"⏱ 현지 체류 약 {st['stayH']}시간" + (f" ({st['nightWhy']})" if st["night"] else "")]
          if st["stayH"] is not None else []),
        *([f"⚠️ {st['warn']}"] if st["warn"] else []),
        "🧳 {airline}, {bagText}".format(**bag_info(o.airline, airlines, o.destination)),
    ]
    link = build_link(o.link, marker)  # 목업은 link가 비어 있어 버튼이 안 붙음
    if link:
        lines.append(f'🔗 <a href="{escape(link)}">가격 확인하기</a>')
    return "\n".join(lines)


def build_messages(deals, marker, today, airlines, cfg, limit=3500, mock=False) -> list:
    """알찬 일정과 밤도깨비 일정을 나눠서 한 통(길면 여러 통)으로 보낸다."""
    if not deals:
        return []
    full = [d for d in deals if not classify(d.offer, d.window, cfg)["night"]]
    night = [d for d in deals if classify(d.offer, d.window, cfg)["night"]]
    test = "[테스트 데이터] " if mock else ""
    blocks = [f"🔥 {test}<b>연차하루면 충분행</b> {today:%m/%d} 특가 {len(deals)}건\n"]
    if full:
        blocks.append(f"\n<b>✈️ 알찬 일정 {len(full)}건</b>\n")
        blocks += ["\n" + format_deal(d, marker, airlines, cfg) + "\n" for d in full]
    if night:
        blocks.append(f"\n<b>🌙 밤도깨비 일정 {len(night)}건</b>\n<i>밤에 도착하거나 아침 일찍 돌아오는 짧고 굵은 일정이에요.</i>\n")
        blocks += ["\n" + format_deal(d, marker, airlines, cfg) + "\n" for d in night]
    msgs, cur = [], ""
    for b in blocks:
        if len(cur) + len(b) > limit:
            msgs.append(cur)
            cur = ""
        cur += b
    msgs.append(cur + FOOTER)
    return msgs


def send_telegram(bot_token, chat_id, text):
    r = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=30,
    )
    r.raise_for_status()
