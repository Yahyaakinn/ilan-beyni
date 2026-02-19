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
DATA_FILE = "sent_news.json"

# 🔑 SINAVLAR
EXAMS = [
    "yks","tyt","ayt","ydt",
    "kpss","ales","dgs","msü",
    "yds","e-yds","tus","ydus",
    "ekpss","dhbt","sts","mbsts",
    "ags","hmbsts"
]

# 🔑 PERSONEL
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

# 🌐 SADECE RESMÎ / GÜVENİLİR KAYNAKLAR
SOURCES = [
    ("https://www.osym.gov.tr/", "ÖSYM"),
    ("https://www.meb.gov.tr/", "MEB"),
    ("https://www.iskur.gov.tr/", "İŞKUR"),
    ("https://www.kamupersonelialimi.com/", "Kamu Personeli"),
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
            "data": {
                "examType": data["examType"],
                "url": data["url"],
                "source": data["source"]
            },
            "android": {"priority": "HIGH"}
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

    if res.status_code != 200:
        print("❌ FCM HATA:", res.text)


# ================== SCRAPER ==================

def generate_news_id(title, source):
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
    return any(e in t for e in EXAMS) or any(k in t for k in EMPLOYMENT_KEYWORDS)


def scrape_site(url, source):
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a"):
            title = " ".join(a.get_text().split())
            link = a.get("href")

            if not title or len(title) < 25:
                continue
            if not link:
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
        print(f"❌ {source} hata:", e)

    return results


# ================== MAIN ==================

def main():
    # 📦 DAHA ÖNCE GÖNDERİLENLER (KALICI HAFIZA)
    sent_ids = set()

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            sent_ids = set(json.load(f))

    new_ids = []

    for url, source in SOURCES:
        news = scrape_site(url, source)

        for item in news:
            if item["id"] in sent_ids:
                continue  # ❌ DAHA ÖNCE GÖNDERİLDİ → BLOKLA

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

    # 💾 HAFIZAYA KAYDET (BİR DAHA ASLA GÖNDERMEZ)
    if new_ids:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sent_ids), f, indent=2)

    print(f"✅ Yeni gönderilen bildirim: {len(new_ids)}")


if __name__ == "__main__":
    main()
