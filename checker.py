import requests
import json
import os
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from google.auth.transport.requests import Request

# ================== CONFIG ==================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID") or "naberr-6f4e4"
SERVICE_ACCOUNT_FILE = "service-account.json"

DATA_FILE = "news.json"

EXAMS = [
    "yks","tyt","ayt","ydt",
    "kpss","ales","dgs","msü",
    "yds","e-yds","tus","ydus",
    "ekpss","dhbt","sts","mbsts",
    "ags","hmbsts",
    "kaymakam","sayıştay",
    "adli yargı","idari yargı",
    "hakimlik","savcılık",
    "bekçi","bekçilik",
    "polis","pmyo","pomem","paem",
    "jandarma","sahil güvenlik",
    "uzman erbaş","astsubay","subay",
    "öğretmen","öğretmenlik","meb",
    "4a","4b","sözleşmeli","kadro"
]

SOURCES = [
    ("https://www.osym.gov.tr/", "ÖSYM"),
    ("https://www.meb.gov.tr/", "MEB"),
    ("https://www.hurriyet.com.tr/", "Hürriyet"),
    ("https://www.sabah.com.tr/", "Sabah"),
    ("https://www.milliyet.com.tr/", "Milliyet")
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
                "body": f"{data['examType']} • {data['deadlineText']}"
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

def detect_exam_type(title):
    t = title.lower()
    for e in EXAMS:
        if e in t:
            return e.upper()
    return "GENEL"


def is_exam_news(title):
    t = title.lower()
    return any(e in t for e in EXAMS) and any(
        k in t for k in ["sınav", "başvuru", "alım", "sonuç", "tercih", "kayıt"]
    )


def scrape_site(url, source):
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a"):
            if len(results) >= 10:
                break

            title = " ".join(a.get_text().split())
            link = a.get("href")

            if not title or len(title) < 20:
                continue
            if not link or link.endswith(".pdf"):
                continue

            if not link.startswith("http"):
                link = url.rstrip("/") + "/" + link.lstrip("/")

            if is_exam_news(title):
                results.append({
                    "source": source,
                    "title": title,
                    "link": link
                })
    except Exception as e:
        print(source, "hata:", e)

    return results


# ================== MAIN ==================

def main():
    old_news = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old_news = json.load(f)

    seen_links = {n["link"] for n in old_news}
    new_items = []

    for url, source in SOURCES:
        for item in scrape_site(url, source):
            if item["link"] not in seen_links:
                new_items.append(item)
                seen_links.add(item["link"])

    # 🔔 SADECE GERÇEK YENİ HABERLER
    for item in new_items:
        exam_type = detect_exam_type(item["title"])
        send_fcm(
            topic=exam_type.lower(),
            data={
                "title": item["title"],
                "examType": exam_type,
                "city": "TÜRKİYE GENELİ",
                "deadlineText": "Yeni ilan yayınlandı",
                "url": item["link"]
            }
        )

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(new_items + old_news, f, ensure_ascii=False, indent=2)

    print("Yeni gönderilen ilan:", len(new_items))


if __name__ == "__main__":
    main()
