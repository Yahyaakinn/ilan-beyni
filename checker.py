import requests
import json
import os
import hashlib
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from urllib.parse import urljoin

# ================== CONFIG ==================

HEADERS = {
“User-Agent”: “Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36”,
“Accept”: “text/html,application/xhtml+xml,application/xml;q=0.9,/;q=0.8”,
“Accept-Language”: “tr-TR,tr;q=0.9,en;q=0.8”,
“Accept-Encoding”: “gzip, deflate, br”,
“Connection”: “keep-alive”,
}

PROJECT_ID = os.getenv(“FIREBASE_PROJECT_ID”) or “naberr-6f4e4”
SERVICE_ACCOUNT_FILE = “service-account.json”
DATA_FILE = “sent_news.json”

EXAMS = [
“yks”, “tyt”, “ayt”, “ydt”,
“kpss”, “ales”, “dgs”, “msu”,
“yds”, “e-yds”, “tus”, “ydus”,
“ekpss”, “dhbt”, “sts”, “mbsts”,
“ags”, “hmbsts”
]

SOURCES = [
(“https://www.osym.gov.tr/TR,33759/2026.html”, “OSYM”),
(“https://www.osym.gov.tr/TR,6/duyurular.html”, “OSYM”),
(“https://www.meb.gov.tr/meb_duyuruindex.php”, “MEB”),
]

RESMI_GAZETE_BASE = “https://www.resmigazete.gov.tr”

# ================== TOKEN CACHE ==================

_cached_token = None
_token_expiry = None

def get_access_token():
global _cached_token, _token_expiry


now = datetime.utcnow()

if _cached_token and _token_expiry and now < _token_expiry:
    return _cached_token

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=["https://www.googleapis.com/auth/firebase.messaging"]
)
credentials.refresh(Request())

_cached_token = credentials.token
_token_expiry = now + timedelta(minutes=50)

return _cached_token


# ================== FIREBASE ==================

def send_fcm(topic, data):
print(f”FCM gonderiliyor -> topic: {topic} | baslik: {data[‘title’]}”)


url = f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send"

payload = {
    "message": {
        "topic": topic,
        "notification": {
            "title": data["title"],
            "body": f"{data['examType']} - Yeni duyuru"
        },
        "data": {
            "examType": data["examType"],
            "url": data["url"],
            "source": data["source"]
        },
        "android": {
            "priority": "HIGH",
            "notification": {
                "sound": "default",
                "channel_id": "exam_notifications"
            }
        },
        "apns": {
            "payload": {
                "aps": {
                    "sound": "default"
                }
            }
        }
    }
}

try:
    res = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=15
    )

    if res.status_code == 200:
        print(f"Bildirim gonderildi: {data['title']}")
    else:
        print(f"FCM HATA [{res.status_code}]: {res.text}")

except Exception as e:
    print(f"FCM istegi basarisiz: {e}")


# ================== SCRAPER ==================

def generate_news_id(title, source):
raw = f”{title.lower().strip()}|{source.lower().strip()}”
return hashlib.sha256(raw.encode(“utf-8”)).hexdigest()

def detect_exam_type(title):
t = title.lower()
for e in EXAMS:
if e in t:
return e.upper()
return “GENEL”

def is_relevant_news(title):
t = title.lower()
return any(e in t for e in EXAMS)

def scrape_site(url, source):
results = []


print(f"  Baglaniliyor: {url}")

try:
    session = requests.Session()
    session.headers.update(HEADERS)

    r = session.get(url, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding

    soup = BeautifulSoup(r.text, "html.parser")
    links = soup.find_all("a", href=True)
    print(f"  Toplam link bulundu: {len(links)}")

    found = 0
    for a in links:
        title = " ".join(a.get_text().split()).strip()
        link = a.get("href", "").strip()

        if not title or len(title) < 15:
            continue
        if not link or link.startswith("javascript:") or link == "#":
            continue

        link = urljoin(url, link)

        if is_relevant_news(title):
            news_id = generate_news_id(title, source)
            results.append({
                "id": news_id,
                "title": title,
                "link": link,
                "source": source,
                "createdAt": datetime.utcnow().isoformat()
            })
            found += 1
            print(f"  Haber bulundu: {title[:80]}")

    print(f"  {source}: {found} ilgili haber bulundu")

except requests.exceptions.ConnectionError:
    print(f"  {source} baglanti hatasi")
except requests.exceptions.Timeout:
    print(f"  {source} zaman asimi")
except requests.exceptions.HTTPError as e:
    print(f"  {source} HTTP hatasi: {e}")
except Exception as e:
    print(f"  {source} beklenmeyen hata: {e}")

return results


# ================== RESMI GAZETE SCRAPER ==================

def scrape_resmi_gazete():
results = []
source = “Resmi Gazete”


dates_to_try = [
    datetime.utcnow(),
    datetime.utcnow() - timedelta(days=1),
    datetime.utcnow() - timedelta(days=2),
    datetime.utcnow() - timedelta(days=3),
]

for dt in dates_to_try:
    year = dt.strftime("%Y")
    month = dt.strftime("%m")
    day = dt.strftime("%Y%m%d")
    url = f"{RESMI_GAZETE_BASE}/eskiler/{year}/{month}/{day}.htm"

    print(f"  Resmi Gazete deneniyor: {url}")

    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        r = session.get(url, timeout=20)

        if r.status_code == 404:
            print(f"  {day} sayisi bulunamadi, onceki gun deneniyor...")
            continue

        r.raise_for_status()
        r.encoding = "windows-1254"

        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.find_all("a", href=True)
        print(f"  Resmi Gazete toplam link: {len(links)}")

        found = 0
        for a in links:
            title = " ".join(a.get_text().split()).strip()
            link = a.get("href", "").strip()

            if not title or len(title) < 15:
                continue
            if not link or link.startswith("javascript:") or link == "#":
                continue

            link = urljoin(url, link)

            if is_relevant_news(title):
                news_id = generate_news_id(title, source)
                results.append({
                    "id": news_id,
                    "title": title,
                    "link": link,
                    "source": source,
                    "createdAt": datetime.utcnow().isoformat()
                })
                found += 1
                print(f"  Resmi Gazete haberi: {title[:80]}")

        print(f"  Resmi Gazete {day}: {found} ilgili haber bulundu")
        break

    except requests.exceptions.ConnectionError:
        print("  Resmi Gazete baglanti hatasi")
        break
    except requests.exceptions.Timeout:
        print("  Resmi Gazete zaman asimi")
        break
    except Exception as e:
        print(f"  Resmi Gazete beklenmeyen hata: {e}")
        break

return results


# ================== MAIN ==================

def main():
print(”=” * 50)
print(“Sinav Duyuru Botu Basladi”)
print(f”Zaman: {datetime.utcnow().isoformat()}”)
print(”=” * 50)


sent_ids = set()
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            sent_ids = set(json.load(f))
        print(f"Daha once gonderilmis {len(sent_ids)} haber yuklendi")
    except Exception as e:
        print(f"sent_news.json okunamadi, sifirdan basliyor: {e}")
else:
    print("sent_news.json bulunamadi, yeni olusturulacak")

new_ids = []
all_news = []

seen_urls = set()
for url, source in SOURCES:
    if url in seen_urls:
        continue
    seen_urls.add(url)

    print(f"\n{source} taranıyor...")
    news = scrape_site(url, source)
    all_news.extend(news)

print("\nResmi Gazete taranıyor...")
rg_news = scrape_resmi_gazete()
all_news.extend(rg_news)

print(f"\nToplam bulunan haber: {len(all_news)}")

for item in all_news:
    if item["id"] in sent_ids:
        continue

    exam_type = detect_exam_type(item["title"])

    send_fcm(
        topic=exam_type.lower(),
        data={
            "title": item["title"],
            "examType": exam_type,
            "url": item["link"],
            "source": item["source"]
        }
    )

    sent_ids.add(item["id"])
    new_ids.append(item["id"])

if new_ids:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sent_ids), f, indent=2, ensure_ascii=False)
        print("\nsent_news.json guncellendi")
    except Exception as e:
        print(f"Kaydetme hatasi: {e}")

print("\n" + "=" * 50)
print(f"Tamamlandi! Yeni gonderilen bildirim: {len(new_ids)}")
print("=" * 50)


if *__name__* == “*main__*”:
main()
