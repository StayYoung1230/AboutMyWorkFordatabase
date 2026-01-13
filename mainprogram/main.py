# -*- coding: utf-8 -*-

import sqlite3
import requests
from datetime import datetime
import time
from bs4 import BeautifulSoup   # <== 新增

DB_NAME = "mydb4final.db"

# 想比較的國家（Steam cc）
REGIONS = {
    "tw": ("Taiwan", "TWD"),
    "us": ("United States", "USD"),
    "jp": ("Japan", "JPY"),
    "gb": ("United Kingdom", "GBP"),
    "de": ("Germany", "EUR"),
    "br": ("Brazil", "BRL"),
    "ru": ("Russia", "RUB"),
}

# Steam Store API
DETAIL_API_URL = "https://store.steampowered.com/api/appdetails"

# Steam 商店搜尋頁
SEARCH_BASE_URL = "https://store.steampowered.com/search/?filter=topsellers"

HEADERS = {"User-Agent": "Mozilla/5.0"}


# 從 Steam 商店搜尋頁抓 appid（
def fetch_appids_from_store(max_pages=20, sleep_sec=0.4):
    """
    從 Steam 商店搜尋頁抓 appid
    max_pages: 最多抓到第幾頁
    sleep_sec: 每頁之間休息時間，避免太兇
    回傳: appid list(不重複)
    """
    all_appids = []
    seen = set()

    for page in range(1, max_pages + 1):
        url = f"{SEARCH_BASE_URL}&page={page}"
        print(f"[Search] 抓取第 {page} 頁: {url}")

        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        rows = soup.select('a.search_result_row[data-ds-appid]')
        if not rows:
            print(f"[Search] 第 {page} 頁沒有結果，停止。")
            break

        new_count = 0
        for a in rows:
            appid_str = a.get("data-ds-appid")
            if not appid_str:
                continue
            appid = int(appid_str)
            if appid in seen:
                continue
            seen.add(appid)
            all_appids.append(appid)
            new_count += 1

        print(f"[Search] 第 {page} 頁新增 {new_count} 個 appid,累計 {len(all_appids)} 個。\n")
        time.sleep(sleep_sec)

    return all_appids


# ============================================================
# 建表
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS Game (
        GameID INTEGER PRIMARY KEY,
        ReleaseDate TEXT,
        IsFree INTEGER,
        RequiredAge INTEGER,
        MainTitle TEXT,
        Edition TEXT,
        SupportedLanguages TEXT
    );

    CREATE TABLE IF NOT EXISTS Developer (
        DevID INTEGER PRIMARY KEY AUTOINCREMENT,
        Name TEXT UNIQUE
    );

    CREATE TABLE IF NOT EXISTS Publisher (
        PubID INTEGER PRIMARY KEY AUTOINCREMENT,
        Name TEXT UNIQUE
    );

    CREATE TABLE IF NOT EXISTS Tag (
        TagID INTEGER PRIMARY KEY,
        TagName TEXT,
        Category TEXT
    );

    CREATE TABLE IF NOT EXISTS Region (
        RegionCode TEXT PRIMARY KEY,
        RegionName TEXT,
        CurrencyCode TEXT
    );

    CREATE TABLE IF NOT EXISTS DeveloperGame (
        DevID INTEGER,
        GameID INTEGER,
        PRIMARY KEY (DevID, GameID)
    );

    CREATE TABLE IF NOT EXISTS PublisherGame (
        PubID INTEGER,
        GameID INTEGER,
        PRIMARY KEY (PubID, GameID)
    );

    CREATE TABLE IF NOT EXISTS GameTag (
        GameID INTEGER,
        TagID INTEGER,
        TagRelevance INTEGER,
        PRIMARY KEY (GameID, TagID)
    );

    CREATE TABLE IF NOT EXISTS PriceRecord (
        PriceRecordID INTEGER PRIMARY KEY AUTOINCREMENT,
        GameID INTEGER NOT NULL,
        RegionCode TEXT NOT NULL,
        OriginalPrice INTEGER,
        FinalPrice INTEGER,
        DiscountPercent INTEGER,
        RecordTime TEXT
    );
    """)

    conn.commit()
    return conn


# ============================================================
# Steam 詳細資料 API
# ============================================================
def fetch_from_steam(app_id, cc="tw"):
    params = {"appids": app_id, "cc": cc, "l": "english"}
    try:
        resp = requests.get(DETAIL_API_URL, headers=HEADERS, params=params, timeout=12)
        data = resp.json()
        entry = data.get(str(app_id), {})
        if not entry.get("success"):
            return None
        return entry.get("data")
    except Exception as e:
        print(f"[ERROR] 呼叫 Steam API 失敗 appid={app_id}, cc={cc}, err={e}")
        return None


# ============================================================
# Insert Region
# ============================================================
def insert_regions(cur):
    for code, (name, curr) in REGIONS.items():
        cur.execute("""
            INSERT OR IGNORE INTO Region VALUES (?, ?, ?)
        """, (code, name, curr))


# ============================================================
# Insert Game / Developer / Publisher / Tag / 關係
# ============================================================
def insert_game_and_related(cur, app_id, data):
    # 檢查資料是否完整，若不完整則跳過插入
    if not data:
        print(f"[WARN] {app_id} 資料不完整，跳過插入。")
        return

    # 確保遊戲的基本資料（如名稱、發行日期）存在
    release_date = data.get("release_date", {}).get("date")
    is_free = 1 if data.get("is_free") else 0
    required_age = int(data.get("required_age") or 0)
    
    # 檢查遊戲名稱是否存在
    full = data.get("name", "")
    if not full:
        print(f"[WARN] {app_id} 遊戲名稱缺失，跳過插入。")
        return
    
    if " - " in full:
        main, edition = full.split(" - ", 1)
    else:
        main, edition = full, None

    langs = data.get("supported_languages", "")

    # 插入 Game 表格資料
    cur.execute("""
        INSERT OR REPLACE INTO Game
        (GameID, ReleaseDate, IsFree, RequiredAge, MainTitle, Edition, SupportedLanguages)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (app_id, release_date, is_free, required_age, main, edition, langs))

    # Developer
    if "developers" in data:
        for dev in data.get("developers", []):
            dev = dev.strip()
            if not dev:
                continue
            cur.execute("INSERT OR IGNORE INTO Developer (Name) VALUES (?)", (dev,))
            cur.execute("SELECT DevID FROM Developer WHERE Name=?", (dev,))
            dev_id = cur.fetchone()[0]
            cur.execute("INSERT OR IGNORE INTO DeveloperGame VALUES (?, ?)", (dev_id, app_id))

    # Publisher
    if "publishers" in data:
        for pub in data.get("publishers", []):
            pub = pub.strip()
            if not pub:
                continue
            cur.execute("INSERT OR IGNORE INTO Publisher (Name) VALUES (?)", (pub,))
            cur.execute("SELECT PubID FROM Publisher WHERE Name=?", (pub,))
            pub_id = cur.fetchone()[0]
            cur.execute("INSERT OR IGNORE INTO PublisherGame VALUES (?, ?)", (pub_id, app_id))

    # Tags (Genres and Categories)
    tag_index = 1

    if "genres" in data:
        # Genres
        for g in data.get("genres", []):
            tid = int(g.get("id"))
            tname = g.get("description")
            cur.execute("""
                INSERT OR IGNORE INTO Tag (TagID, TagName, Category)
                VALUES (?, ?, 'Genre')
            """, (tid, tname))
            cur.execute("""
                INSERT OR IGNORE INTO GameTag VALUES (?, ?, ?)
            """, (app_id, tid, tag_index))
            tag_index += 1

    if "categories" in data:
        # Categories
        for c in data.get("categories", []):
            tid = int(c.get("id"))
            tname = c.get("description")
            cur.execute("""
                INSERT OR IGNORE INTO Tag (TagID, TagName, Category)
                VALUES (?, ?, 'Feature')
            """, (tid, tname))
            cur.execute("""
                INSERT OR IGNORE INTO GameTag VALUES (?, ?, ?)
            """, (app_id, tid, tag_index))
            tag_index += 1


# ============================================================
# Insert PriceRecord（免費遊戲 = 0 元）
# ============================================================
def insert_price(cur, app_id, region_code, data):
    p = data.get("price_overview")

    if p is None:
        # 免費遊戲 or 無價格資料 → 當作 0 元
        orig = 0
        final = 0
        disc = 0
    else:
        orig = int(p["initial"] / 100)
        final = int(p["final"] / 100)
        disc = p["discount_percent"]

    cur.execute("""
        INSERT INTO PriceRecord
        (GameID, RegionCode, OriginalPrice, FinalPrice, DiscountPercent, RecordTime)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (app_id, region_code, orig, final, disc, datetime.utcnow().isoformat(" ")))


# ============================================================
# 主程式
# ============================================================
def main():
    # 1) 先從 Steam 商店抓 appid
    MAX_PAGES = 20  # 你可以改這裡：最多抓幾頁搜尋結果
    app_ids = fetch_appids_from_store(max_pages=MAX_PAGES)
    print(f"\n[Main] 本次總共要處理 {len(app_ids)} 個 appid。\n")

    conn = init_db()
    cur = conn.cursor()

    insert_regions(cur)
    conn.commit()

    # 2) 依照 app_ids 逐一呼叫 Steam API 寫進 DB
    for app_id in app_ids:
        print(f"\n===============================")
        print(f"處理遊戲：{app_id}")
        print(f"===============================\n")

        first_ok_data = None

        for cc in REGIONS.keys():
            data = fetch_from_steam(app_id, cc)

            if data is None:
                print(f"[WARN] {app_id} {cc} 無資料")
                continue

            if first_ok_data is None:
                first_ok_data = data
                insert_game_and_related(cur, app_id, data)

            insert_price(cur, app_id, cc, data)
            time.sleep(0.1)

        conn.commit()

        # 顯示各國價格（純確認用，你之後也可以拿掉）
        print(f"\n=== {app_id} 各國價格比較 ===")
        cur.execute("""
            SELECT RegionCode, OriginalPrice, FinalPrice, DiscountPercent
            FROM PriceRecord
            WHERE GameID = ?
        """, (app_id,))
        rows = cur.fetchall()

        valid = [x for x in rows if x[2] is not None]
        minp = min([x[2] for x in valid]) if valid else None

        for rc, op, fp, disc in rows:
            flag = "<-- 最低價" if (fp is not None and fp == minp) else ""
            print(f"{rc.upper():>2} | {fp} | 折扣 {disc}% {flag}")

    conn.close()


if __name__ == "__main__":
    main()
