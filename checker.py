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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,/;q=0.8",
}

PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID") or "naberr-6f4e4"
SERVICE_ACCOUNT_FILE = "service-account.json"
DATA_FILE = "sent_news.json"

EXAMS = [
    "yks", "tyt", "ayt", "ydt",
    "kpss", "ales", "dgs", "msu",
    "yds", "e-yds", "tus", "ydus",
    "ekpss", "dhbt", "sts", "mbsts",
    "ags", "hmbsts"
]

SOURCES = [
    ("https://www.osym.gov.tr/TR,33759/2026.html", "OSYM"),
    ("https://www.meb.gov.tr/meb_duyuruindex.php", "MEB"),
]

RESMI_GAZETE_BASE = "https://www.resmigazete.gov.tr"

# ================== FIREBASE ==================

def get_access_token():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/firebase.messaging"]
    )
    credentials.refresh(Request())
    return credentials.token

def send_fcm(topic, data):
    print(f"📣 FCM -> {topic} | {data['title']}")
    url = f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send"
    
    payload = {
        "message": {
            "topic": topic,
            "notification": {
                "title": data["title"],
                "body": f"{data['examType']} • Yeni duyuru"
            },
            "data": {
                "examType": data["examType"],
                "url": data["url"],
                "source": data["source"]
            },
            "android": {"priority": "HIGH"}
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
        if res.status_code != 200:
            print("❌ FCM HATA:", res.text)
    except Exception as e:
        print(f"❌ FCM Bağlantı Hatası: {e}")

# ================== SCRAPER TOOLS ==================

def generate_news_id(title, source):
    raw = f"{title.lower().strip()}|{source.lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def detect_exam_type(title):
    t = title.lower()
    for e in EXAMS:
        if e in t:
            return e.upper()
    return "GENEL"

def is_relevant_news(title):
    t = title.lower()
    return any(e in t for e in EXAMS)

# ================== SCRAPERS ==================

def scrape_site(url, source):
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        r.encoding = r.apparent_encoding # Karakter kodlamasını otomatik çöz
        
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.find_all("a", href=True)

        for a in links[:60]:
            title = " ".join(a.get_text().split()).strip()
            link = a.get("href")

            if not title or len(title) < 15 or not link:
                continue

            link = urljoin(url, link)

            if is_relevant_news(title):
                results.append({
                    "id": generate_news_id(title, source),
                    "title": title,
                    "link": link,
                    "source": source
                })
    except Exception as e:
        print(f"❌ {source} hata: {e}")
    return results

def scrape_resmi_gazete():
    """Resmi Gazete'nin bugünkü sayısını tarar."""
    results = []
    source = "Resmi Gazete"
    
    # Bugünün tarihine göre URL oluştur (Örn: /eskiler/2024/05/20240522.htm)
    now = datetime.utcnow() + timedelta(hours=3) # Türkiye saati ayarı
    year, month, day = now.strftime("%Y"), now.strftime("%m"), now.strftime("%Y%m%d")
    url = f"{RESMI_GAZETE_BASE}/eskiler/{year}/{month}/{day}.htm"
    
    print(f"🔎 Resmi Gazete taranıyor: {day} sayısı...")

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        
        # Eğer bugün henüz gazete çıkmadıysa veya hafta sonuysa 404 dönebilir
        if r.status_code == 404:
            print("ℹ️ Bugünün Resmi Gazete sayısı henüz yayınlanmadı.")
            return results
            
        r.raise_for_status()
        r.encoding = "windows-1254" # Resmi Gazete genelde bu kodlamayı kullanır
        
        soup = BeautifulSoup(r.text, "html.parser")
        # Resmi Gazete'de duyurular genelde <a> etiketleri içindedir
        links = soup.find_all("a", href=True)

        for a in links:
            title = " ".join(a.get_text().split()).strip()
            link = a.get("href")

            if not title or len(title) < 15:
                continue

            # Linkleri tam URL'ye çevir
            full_link = urljoin(url, link)

            if is_relevant_news(title):
                results.append({
                    "id": generate_news_id(title, source),
                    "title": title,
                    "link": full_link,
                    "source": source
                })
    except Exception as e:
        print(f"❌ Resmi Gazete hata: {e}")
    
    return results

# ================== MAIN ==================

def main():
    sent_ids = set()
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                sent_ids = set(json.load(f))
            except: sent_ids = set()

    all_news = []

    # Standart Kaynaklar (ÖSYM, MEB)
    for url, source in SOURCES:
        print(f"🔎 {source} taranıyor...")
        all_news.extend(scrape_site(url, source))

    # Resmi Gazete
    all_news.extend(scrape_resmi_gazete())

    new_count = 0
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
        new_count += 1

    if new_count > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sent_ids), f, indent=2, ensure_ascii=False)

    print(f"✅ İşlem tamamlandı. Yeni gönderilen bildirim: {new_count}")

if __name__ == "__main__":
    main()
