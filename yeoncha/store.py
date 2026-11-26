"""가격 이력과 발송 기록을 SQLite에 저장. 파일 하나라 GitHub 저장소에 커밋해서 보존한다."""
import sqlite3
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    origin TEXT, destination TEXT, depart TEXT, ret TEXT, nights INTEGER,
    price INTEGER, airline TEXT, transfers INTEGER, link TEXT, observed TEXT,
    PRIMARY KEY (origin, destination, depart, ret, observed)
);
CREATE INDEX IF NOT EXISTS idx_route ON prices (origin, destination, observed);
CREATE TABLE IF NOT EXISTS alerts (
    origin TEXT, destination TEXT, depart TEXT, ret TEXT, price INTEGER, sent TEXT,
    PRIMARY KEY (origin, destination, depart, ret)
);
"""


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def is_empty(self) -> bool:
        return self.db.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 0

    def save_offers(self, offers, observed: date):
        """같은 날 같은 여정은 최저가만 남긴다."""
        self.db.executemany(
            """INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(origin, destination, depart, ret, observed) DO UPDATE SET
                 price=excluded.price, airline=excluded.airline,
                 transfers=excluded.transfers, link=excluded.link
               WHERE excluded.price < prices.price""",
            [(o.origin, o.destination, o.depart, o.ret,
              (date.fromisoformat(o.ret) - date.fromisoformat(o.depart)).days,
              o.price, o.airline, o.transfers, o.link, observed.isoformat()) for o in offers],
        )
        self.db.commit()

    def route_prices(self, origin, dest, since: date, nights=None) -> list:
        q = "SELECT price FROM prices WHERE origin=? AND destination=? AND observed>=?"
        args = [origin, dest, since.isoformat()]
        if nights is not None:
            q += " AND nights=?"
            args.append(nights)
        return [r[0] for r in self.db.execute(q, args)]

    def trip_prices_before(self, origin, dest, depart, ret, today: date) -> list:
        return [r[0] for r in self.db.execute(
            "SELECT price FROM prices WHERE origin=? AND destination=? AND depart=? AND ret=? AND observed<?",
            (origin, dest, depart, ret, today.isoformat()))]

    def last_alert_price(self, origin, dest, depart, ret):
        r = self.db.execute(
            "SELECT price FROM alerts WHERE origin=? AND destination=? AND depart=? AND ret=?",
            (origin, dest, depart, ret)).fetchone()
        return r[0] if r else None

    def record_alert(self, offer, sent: date):
        self.db.execute(
            "INSERT OR REPLACE INTO alerts VALUES (?,?,?,?,?,?)",
            (offer.origin, offer.destination, offer.depart, offer.ret, offer.price, sent.isoformat()))
        self.db.commit()
