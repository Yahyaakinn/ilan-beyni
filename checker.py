import requests
import json
import os
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

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

DATA_FILE = "news.json"


def detect_exam_type(title):
    t = title.lower()
    for e in EXAMS:
        if e in t:
            return e.upper()
    return "GENEL"


def is_exam_news(title):
    t = title.lower()
    has_exam = any(e in t for e in EXAMS)
    has_action = any(k in t for k in [
        "sınav", "başvuru", "alım", "sonuç", "tercih", "kayıt"
    ])
    return has_exam and has_action


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


def send_push_event(item):
    if not os.getenv("ONESIGNAL_APP_ID"):
        return

    payload = {
        "app_id": os.getenv("ONESIGNAL_APP_ID"),
        "included_segments": ["All"],
        "headings": {"en": "Yeni Sınav / Alım"},
        "contents": {"en": item["title"]},
        "data": {
            "title": item["title"],
            "description": item["title"],
            "examType": detect_exam_type(item["title"]),
            "city": "TÜRKİYE GENELİ",
            "education": "Genel",
            "startDate": datetime.now().isoformat(),
            "endDate": (datetime.now() + timedelta(days=7)).isoformat(),
            "source": item["source"],
            "sourceUrl": item["link"],
            "url": item["link"]
        }
    }

    requests.post(
        "https://onesignal.com/api/v1/notifications",
        headers={
            "Authorization": f"Basic {os.getenv('ONESIGNAL_API_KEY')}",
            "Content-Type": "application/json"
        },
        json=payload
    )


def main():
    old_news = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old_news = json.load(f)

    seen = {n["link"] for n in old_news}
    new_items = []

    for url, source in SOURCES:
        for item in scrape_site(url, source):
            if item["link"] not in seen:
                new_items.append(item)
                seen.add(item["link"])

    if new_items:
        send_push_event(new_items[0])

    all_news = new_items + old_news

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_news, f, ensure_ascii=False, indent=2)

    print("Toplam ilan:", len(all_news))


if __name__ == "__main__":
    main()
