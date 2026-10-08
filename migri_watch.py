#!/usr/bin/env python3
"""
Migri randevu takipçisi
-----------------------
Migri'nin randevu sistemini (migri.vihta.com) kontrol eder; Helsinki veya Turku'da
boş randevu bulursa ntfy.sh üzerinden telefona anlık bildirim gönderir.

Kullanım:
  python migri_watch.py --discover       # servisleri ve ofisleri listeler (ilk kurulum kontrolü)
  python migri_watch.py --test-notify    # telefona deneme bildirimi yollar
  python migri_watch.py                  # bir kez kontrol eder (GitHub Actions bunu çalıştırır)
  python migri_watch.py --loop 180       # kendi bilgisayarında: her 180 sn'de bir kontrol

Ayarlar (ortam değişkenleri):
  NTFY_TOPIC     zorunlu – ntfy uygulamasında abone olduğun gizli konu adı
  CITIES         varsayılan "Helsinki,Turku"
  WEEKS_AHEAD    kaç hafta ileriye bakılacak (varsayılan 12)
  BEFORE_DATE    sadece bu tarihten ÖNCEKİ randevular (ör. 2026-11-18). Boşsa hepsi.
  SERVICE_ID     vatandaşlık servisinin ID'si. Boşsa otomatik bulunmaya çalışılır.
  SERVICE_KEYWORDS  otomatik bulma için anahtar kelimeler (varsayılan aşağıda)
  STATE_FILE     daha önce bildirilen randevuların kaydı (tekrar bildirim olmasın diye)
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://migri.vihta.com/public/migri"
API = BASE + "/api"
BOOKING_URL = "https://migri.fi/en/book-an-appointment"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
CITIES = [c.strip().lower() for c in os.environ.get("CITIES", "Helsinki,Turku").split(",") if c.strip()]
WEEKS_AHEAD = int(os.environ.get("WEEKS_AHEAD", "12"))
BEFORE_DATE = os.environ.get("BEFORE_DATE", "").strip() or "2027-01-08"  # 7 Ocak dahil
SERVICE_ID = os.environ.get("SERVICE_ID", "").strip()
SERVICE_KEYWORDS = [k.strip().lower() for k in os.environ.get(
    "SERVICE_KEYWORDS",
    "citizenship,kansalaisuus,medborgarskap").split(",") if k.strip()]
STATE_FILE = os.environ.get("STATE_FILE", "seen_slots.json")

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://migri.vihta.com",
    "referer": BASE + "/",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- Migri API
class Migri:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.s.get(BASE + "/", timeout=30)
        r = self.s.get(API + "/sessions", params={"language": "en"}, timeout=30)
        r.raise_for_status()
        self.s.headers["vihta-session"] = r.json()["id"]

    def get_json(self, path, **params):
        r = self.s.get(API + path, params=params or None, timeout=30)
        if not r.ok:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def body(self, service_id):
        return json.dumps({
            "serviceSelections": [{"firstName": "", "lastName": "", "values": [service_id]}],
            "extraServices": [],
        })

    def localities(self, service_id):
        r = self.s.post(API + "/services/localities", data=self.body(service_id), timeout=30)
        r.raise_for_status()
        return r.json().get("localities", [])

    def week(self, office_id, service_id, day):
        y, w, _ = day.isocalendar()
        r = self.s.post(f"{API}/scheduling/offices/{office_id}/{y}/w{w}",
                        params={"start_hours": 0, "end_hours": 24},
                        data=self.body(service_id), timeout=30)
        if not r.ok:
            log(f"  hafta {w}: HTTP {r.status_code}")
            return []
        data = r.json()
        slots = []
        for day_list in data.get("dailyTimesByOffice") or []:
            for slot in day_list or []:
                ts = slot.get("startTimestamp")
                if ts:
                    slots.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        return slots


def walk(obj, path=()):
    """JSON içindeki tüm dict'leri gezer."""
    if isinstance(obj, dict):
        yield obj, path
        for k, v in obj.items():
            yield from walk(v, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (str(i),))


def find_services(m):
    """Servis listesini birkaç olası adresten çekip id+isim çiftlerini döndürür."""
    found = {}
    for path in ("/services", "/service-categories", "/serviceCategories",
                 "/services/categories", "/configuration", "/settings"):
        data = m.get_json(path, language="en")
        if data is None:
            continue
        for d, _ in walk(data):
            sid = d.get("id")
            name = " ".join(str(d.get(k, "")) for k in ("name", "title", "description")
                            if isinstance(d.get(k), str))
            if isinstance(sid, str) and UUID_RE.match(sid) and name.strip():
                found[sid] = name.strip()
    return found


def pick_service(m):
    if SERVICE_ID:
        return SERVICE_ID
    services = find_services(m)
    matches = [(sid, n) for sid, n in services.items()
               if any(k in n.lower() for k in SERVICE_KEYWORDS)]
    if not matches:
        sys.exit("Vatandaşlık servisi otomatik bulunamadı. README'deki 'SERVICE_ID nasıl bulunur' "
                 "adımını uygula ve SERVICE_ID ayarını gir.")
    # En kısa / en spesifik isim genelde doğru olandır; hepsini logla.
    for sid, n in matches:
        log(f"  aday servis: {sid}  {n}")
    return matches[0][0]


# ---------------------------------------------------------------- bildirim
def notify(title, message, priority="urgent"):
    if not NTFY_TOPIC:
        log("NTFY_TOPIC yok, bildirim atlanıyor:", title, message)
        return
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}",
                  data=message.encode("utf-8"),
                  headers={"Title": title.encode("utf-8"),
                           "Priority": priority,
                           "Tags": "rotating_light",
                           "Click": BOOKING_URL},
                  timeout=30)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_state(seen):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(seen)[-2000:], f)


# ---------------------------------------------------------------- ana akış
def check_once():
    m = Migri()
    service = pick_service(m)
    offices = []
    for loc in m.localities(service):
        if any(c in (loc.get("name") or "").lower() for c in CITIES):
            for o in loc.get("offices", []):
                offices.append((o["id"], o.get("name") or loc.get("name")))
    if not offices:
        log("Uyarı: Helsinki/Turku ofisi bu servis için listede yok.")
        return

    limit = None
    if BEFORE_DATE:
        limit = datetime.fromisoformat(BEFORE_DATE).replace(tzinfo=timezone.utc)

    today = datetime.now(timezone.utc)
    start = today - timedelta(days=today.weekday())
    weeks = WEEKS_AHEAD
    if limit is not None:  # son tarihe kadar olan tüm haftaları kapsa
        weeks = max(1, (limit - start).days // 7 + 1)
    found = []
    for office_id, office_name in offices:
        for i in range(weeks):
            for t in m.week(office_id, service, start + timedelta(weeks=i)):
                if t > today and (limit is None or t < limit):
                    found.append((t, office_name))
            time.sleep(0.5)  # sunucuyu yormamak için

    found.sort()
    log(f"{len(offices)} ofis tarandı, {len(found)} uygun randevu bulundu.")
    seen = load_state()
    new = [(t, o) for t, o in found if f"{o}|{t.isoformat()}" not in seen]
    if new:
        lines = [f"{o}: {t.astimezone().strftime('%d.%m.%Y %H:%M')}" for t, o in new[:10]]
        more = f"\n(+{len(new) - 10} tane daha)" if len(new) > 10 else ""
        notify("Migri: Helsinki/Turku randevusu açıldı!",
               "\n".join(lines) + more + "\nHemen rezervasyon yap → migri.fi")
        log("BİLDİRİM GÖNDERİLDİ:\n" + "\n".join(lines))
        seen.update(f"{o}|{t.isoformat()}" for t, o in new)
        save_state(seen)


def discover():
    m = Migri()
    services = find_services(m)
    print(f"\n{len(services)} servis bulundu:")
    for sid, n in sorted(services.items(), key=lambda x: x[1]):
        mark = "  <-- vatandaşlık?" if any(k in n.lower() for k in SERVICE_KEYWORDS) else ""
        print(f"  {sid}  {n[:90]}{mark}")
    sid = SERVICE_ID or next((s for s, n in services.items()
                              if any(k in n.lower() for k in SERVICE_KEYWORDS)), None)
    if sid:
        print(f"\n{sid} için ofisler:")
        for loc in m.localities(sid):
            for o in loc.get("offices", []):
                print(f"  {loc.get('name')}: {o.get('name')} ({o['id']})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--discover", action="store_true")
    p.add_argument("--test-notify", action="store_true")
    p.add_argument("--loop", type=int, default=0, help="saniye; 0 = bir kez çalış")
    a = p.parse_args()

    if a.test_notify:
        notify("Migri takipçisi çalışıyor ✅", "Bu bir deneme bildirimidir.", priority="default")
        return log("Deneme bildirimi gönderildi.")
    if a.discover:
        return discover()

    while True:
        try:
            check_once()
        except Exception as e:  # ağ hatası vs. — döngü devam etsin
            log("Hata:", e)
            if not a.loop:
                raise
        if not a.loop:
            break
        time.sleep(max(60, a.loop))


if __name__ == "__main__":
    main()
