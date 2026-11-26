"""항공사 코드 → 이름·수하물 안내.
가격 데이터에 수하물 정보가 없어서, 항공사의 '가장 싼 운임' 규정과 지역별 사전구매 요금표로 추정한다."""
import json
from pathlib import Path


def load_airlines(path, mock=False) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    region_of = {city: r for r, cities in data.get("regions", {}).items() for city in cities}
    return {"airlines": data["airlines"], "region_of": region_of, "checked": data.get("checked")}


def bag_info(code, table, dest=None) -> dict:
    a = table["airlines"].get(code)
    if not a:
        return {"airline": code or "항공사 미확인", "bag": "unknown", "addon": None,
                "bagText": "수하물 규정은 예약 화면에서 확인하세요"}
    if a["type"] == "FSC":
        return {"airline": a["name"], "bag": "included", "addon": 0, "bagText": "위탁수하물 포함"}
    if a.get("free_kg", 0) >= 15:
        return {"airline": a["name"], "bag": "included", "addon": 0,
                "bagText": f"위탁수하물 {a['free_kg']}kg 포함"}
    oneway = a.get("bag15_oneway", {}).get(table["region_of"].get(dest))
    addon = oneway * 2 if oneway else None
    text = "최저가는 위탁수하물 미포함일 수 있어요"
    if addon:
        text += f", 15kg 왕복 추가 약 {addon:,}원(편도 {oneway:,}원×2)"
    return {"airline": a["name"], "bag": "lcc", "addon": addon, "bagText": text}
