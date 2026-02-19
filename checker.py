import requests
import json
import os
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from google.auth.transport.requests import Request

# ================== CONFIG ==================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID") or "naberr-6f4e4"
SERVICE_ACCOUNT_FILE = "service-account.json"

DATA_FILE = "news.json"  # STATE DOSYASI

# 🔑 SINAV + PERSONEL KELİMELERİ
EXAMS = [
    "yks","tyt","ayt","ydt",
    "kpss","ales","dgs","msü",
    "yds","e-yds","tus","ydus",
    "ekpss","dhbt","sts","mbsts",
    "ags","hmbsts"
]

EMPLOYMENT_KEYWORDS = [
    "personel alımı",
    "kamu personeli",
    "memur alımı",
    "işçi alımı",
    "sözleşmeli",
    "kadro",
    "4a",
    "4b",
    "4/c",
    "657 sayılı"
]

# 🌐 KAYNAKLAR (KAYNAK ZORUNLU)
SOURCES = [
    ("https://www.osym.gov.tr/", "ÖSYM"),
    ("https://www.meb.gov.tr/", "MEB"),
    ("https://www.hurriyet.com.tr/", "Hürriyet"),
    ("https://www.sabah.com.tr/", "Sabah"),
    ("https://www.milliyet.com.tr/", "Milliyet"),
    ("https://www.kamupersonelialimi.com/", "Kamu Personeli"),
    ("https://www.guncelisilanlari.com/", "Güncel İş İlanları"),
]

# ================== FIREBASE ==================

def get_access_token():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/firebase.messaging"]
    )
    credentials.refresh(Request())
    return credentials.token


def send_fcm(topic, data):
    print(f"📣 FCM → {topic} | {data['title']}")

    url = f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send"

    payload = {
        "message": {
            "topic": topic,
            "notification": {
                "title": data["title"],
                "body": f"{data['examType']} • Yeni ilan"
            },
            "data": data,
            "android": {"priority": "HIGH"},
            "apns": {
                "payload": {
                    "aps": {"sound": "default"}
                }
            }
        }
    }

    res = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=15
    )

    print("FCM STATUS:", res.status_code)
    if res.status_code != 200:
        print(res.text)

# ================== SCRAPER ==================

def generate_news_id(title, source):
    """
    🔑 TEKİL HABER KİMLİĞİ
    Aynı başlık + aynı kaynak = TEK HABER
    """
    raw = f"{title.lower().strip()}|{source.lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def detect_exam_type(title):
    t = title.lower()

    if "4a" in t:
        return "4A"
    if "4b" in t:
        return "4B"
    if any(k in t for k in EMPLOYMENT_KEYWORDS):
        return "PERSONEL"

    for e in EXAMS:
        if e in t:
            return e.upper()

    return "GENEL"


def is_relevant_news(title):
    t = title.lower()
    return any(e in t for e in EXAMS) or any(j in t for j in EMPLOYMENT_KEYWORDS)


def scrape_site(url, source):
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a"):
            title = " ".join(a.get_text().split())
            link = a.get("href")

            if not title or len(title) < 20:
                continue
            if not link or link.endswith(".pdf"):
                continue

            if not link.startswith("http"):
                link = url.rstrip("/") + "/" + link.lstrip("/")

            if is_relevant_news(title):
                results.append({
                    "id": generate_news_id(title, source),
                    "title": title,
                    "link": link,
                    "source": source,
                    "createdAt": datetime.utcnow().isoformat()
                })
    except Exception as e:
        print(source, "hata:", e)

    return results

# ================== MAIN ==================

def main():
    # 📦 ÖNCEKİ STATE
    old_news = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old_news = json.load(f)

    seen_ids = {n["id"] for n in old_news}
    new_items = []

    # 🌐 TÜM KAYNAKLARI TARA
    for url, source in SOURCES:
        for item in scrape_site(url, source):
            if item["id"] not in seen_ids:
                new_items.append(item)
                seen_ids.add(item["id"])

    # 🚫 İLK ÇALIŞTIRMA KORUMASI
    if not old_news:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(new_items, f, ensure_ascii=False, indent=2)
        print("📦 İlk çalıştırma: state oluşturuldu, bildirim atılmadı.")
        return

    # 🔔 SADECE GERÇEKTEN YENİ HABERLER
    for item in new_items:
        exam_type = detect_exam_type(item["title"])
        topic = exam_type.lower()

        send_fcm(
            topic=topic,
            data={
                "title": item["title"],
                "examType": exam_type,
                "city": "TÜRKİYE GENELİ",
                "deadlineText": "Yeni ilan yayınlandı",
                "url": item["link"],
                "source": item["source"]
            }
        )

    # 💾 STATE GÜNCELLE
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(new_items + old_news, f, ensure_ascii=False, indent=2)

    print("✅ Yeni gönderilen ilan:", len(new_items))


if __name__ == "__main__":
    main()
