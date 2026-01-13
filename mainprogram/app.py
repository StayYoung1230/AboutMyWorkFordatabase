import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, render_template, request

app = Flask(__name__)

# 資料庫名稱（請確保 mydb4final.db 與 app.py 放在同一個資料夾）
DB_NAME = "mydb4final.db"

# 國碼 → 中文名稱
REGION_MAP_CH = {
    "tw": "台灣",
    "us": "美國",
    "jp": "日本",
    "gb": "英國",
    "de": "德國",
    "br": "巴西",
    "ru": "俄羅斯",
}

# 國碼 → 幣別
CURRENCY_MAP = {
    "tw": "TWD",
    "us": "USD",
    "jp": "JPY",
    "gb": "GBP",
    "de": "EUR",
    "br": "BRL",
    "ru": "RUB",
}

# 幣別 → 對 TWD 的簡易匯率（粗略換算；要更精準可改成即時/歷史匯率）
FX_TO_TWD = {
    "TWD": 1.0,
    "USD": 30.0,
    "JPY": 0.2,
    "GBP": 38.0,
    "EUR": 33.0,
    "BRL": 6.0,
    "RUB": 0.35,
}


def _safe_int(value: str, default: Optional[int] = None) -> Optional[int]:
    """把使用者輸入安全轉成 int；空字串或非數字就回 default。"""
    if value is None:
        return default
    s = value.strip()
    if s == "":
        return default
    try:
        return int(s)
    except ValueError:
        return default


def _price_to_twd(region_code: Optional[str], price: float) -> Tuple[int, str]:
    """(region_code, price) -> (twd_int, currency_code)"""
    currency = CURRENCY_MAP.get(region_code or "", "TWD")
    rate = FX_TO_TWD.get(currency, 1.0)
    twd = int(round(float(price) * float(rate)))
    return twd, currency


# ---------- 資料載入：遊戲名稱 / Tag 名稱 ----------

def load_all_game_names() -> List[str]:
    """載入所有遊戲名稱，用於 datalist 自動完成。"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT MainTitle FROM Game ORDER BY MainTitle")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows if r[0] is not None]


def load_all_tags() -> List[str]:
    """載入所有 TagName，用於 datalist 自動完成（你的 DB 結構：Tag(TagID, TagName, Category)）。"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT TagName
        FROM Tag
        WHERE TagName IS NOT NULL AND TRIM(TagName) <> ''
        ORDER BY TagName
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows if r[0] is not None]


def _get_game_ids_by_tag(conn: sqlite3.Connection, tag_keyword: str) -> List[int]:
    """
    用 TagName 查 GameID（你的 DB 結構：GameTag(GameID, TagID, TagRelevance) + Tag(TagID, TagName)）

    支援：
    - 單一關鍵字：例如 "Action"
    - 多個 tag：用逗號分隔，例如 "Action, RPG"（採 OR：任一 tag 命中就算）
    """
    tag_keyword = (tag_keyword or "").strip()
    if not tag_keyword:
        return []

    parts = [p.strip() for p in tag_keyword.replace("，", ",").split(",") if p.strip()]
    if not parts:
        return []

    cur = conn.cursor()
    where = " OR ".join(["T.TagName LIKE ?"] * len(parts))
    params = [f"%{p}%" for p in parts]

    cur.execute(
        f"""
        SELECT DISTINCT GT.GameID
        FROM GameTag GT
        JOIN Tag T ON T.TagID = GT.TagID
        WHERE {where}
        """,
        params,
    )
    return [int(r[0]) for r in cur.fetchall()]


# ---------- 核心：搜尋（以 TWD 範圍為準） ----------

def search_games(
    name_keyword: str,
    tag_keyword: str,
    min_price_twd: int,
    max_price_twd: Optional[int],
) -> List[Dict[str, Any]]:
    """
    修正版搜尋邏輯：
    1) 價格範圍是 TWD → 不在 SQL 用 FinalPrice（原幣）去篩，避免錯殺。
    2) 先依「名稱 / Tag」把候選 GameID 篩出來，再把每款遊戲各區價格撈出來換算 TWD。
    3) 每款遊戲以「最低 TWD」作為該遊戲最低價；地區也取最低價那筆對應的地區。
    4) 免費判斷：優先看 PriceRecord 是否存在 0 元；也會參考 Game.IsFree。

    另外：你的 Game.GameID 本身就是 Steam appid，可直接拿來組 Steam 連結。
    """

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # 先用 tag 找候選 GameID（可為空）
    tag_game_ids: Optional[List[int]] = None
    if tag_keyword.strip():
        tag_game_ids = _get_game_ids_by_tag(conn, tag_keyword)
        if not tag_game_ids:
            conn.close()
            return []

    sql = """
        SELECT
            G.GameID,
            G.MainTitle,
            G.IsFree,
            P.RegionCode,
            P.FinalPrice
        FROM Game G
        LEFT JOIN PriceRecord P ON G.GameID = P.GameID
        WHERE 1=1
    """
    params: List[Any] = []

    if name_keyword:
        sql += " AND G.MainTitle LIKE ? "
        params.append(f"%{name_keyword}%")

    if tag_game_ids is not None:
        placeholders = ",".join(["?"] * len(tag_game_ids))
        sql += f" AND G.GameID IN ({placeholders}) "
        params.extend(tag_game_ids)

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    conn.close()

    # group by game
    grouped: Dict[int, Dict[str, Any]] = {}
    for game_id, title, is_free, region_code, final_price in rows:
        if game_id not in grouped:
            grouped[game_id] = {"title": title, "is_free": int(is_free or 0), "records": []}
        grouped[game_id]["records"].append((region_code, final_price))

    results: List[Dict[str, Any]] = []

    for game_id, info in grouped.items():
        appid = int(game_id)  # Steam appid
        title: str = info["title"]
        is_free_flag: int = info["is_free"]
        records: List[Tuple[Optional[str], Optional[float]]] = info["records"]

        has_any_price_value = any(p is not None for _, p in records)

        positive_candidates: List[Tuple[int, str, float, str]] = []  # (twd, region, orig, currency)
        has_zero_price = False

        for region_code, final_price in records:
            if final_price is None:
                continue
            try:
                p = float(final_price)
            except (TypeError, ValueError):
                continue

            if p <= 0:
                has_zero_price = True
                continue

            if region_code is None:
                continue

            twd, currency = _price_to_twd(region_code, p)
            positive_candidates.append((twd, region_code, p, currency))

        if positive_candidates:
            positive_candidates.sort(key=lambda x: (x[0], x[2], x[1]))
            twd_min, region_code, orig_price, currency = positive_candidates[0]
            if currency == "TWD":
                price_str = f"{int(round(orig_price))} TWD"
            else:
                price_str = f"{int(round(orig_price))} {currency} (約 {twd_min} TWD)"
            region_ch = REGION_MAP_CH.get(region_code, region_code)
        else:
            if (has_any_price_value and has_zero_price) or is_free_flag == 1:
                twd_min = 0
                price_str = "免費"
                region_ch = "—"
            else:
                continue

        if twd_min < min_price_twd:
            continue
        if max_price_twd is not None and twd_min > max_price_twd:
            continue

        results.append(
            {
                "appid": appid,        # ⭐ 新增：給前端組 Steam URL
                "title": title,
                "price": price_str,
                "region": region_ch,
                "_twd": twd_min,
            }
        )

    results.sort(key=lambda x: (x["_twd"], x["title"].lower() if isinstance(x.get("title"), str) else ""))

    for r in results:
        r.pop("_twd", None)

    return results


@app.route("/", methods=["GET", "POST"])
def index():
    all_games = load_all_game_names()
    all_tags = load_all_tags()

    error_message: Optional[str] = None

    form_values = {
        "name_keyword": "",
        "tag_keyword": "",
        "min_price": "",
        "max_price": "",
    }

    if request.method == "POST":
        name_keyword = (request.form.get("name_keyword") or "").strip()
        tag_keyword = (request.form.get("tag_keyword") or "").strip()

        min_price_raw = (request.form.get("min_price") or "").strip()
        max_price_raw = (request.form.get("max_price") or "").strip()

        form_values["name_keyword"] = name_keyword
        form_values["tag_keyword"] = tag_keyword
        form_values["min_price"] = min_price_raw
        form_values["max_price"] = max_price_raw

        min_price_twd = _safe_int(min_price_raw, 0)
        max_price_twd = _safe_int(max_price_raw, None)

        if min_price_twd is None:
            error_message = "價格輸入格式有誤。"
        elif min_price_twd < 0 or (max_price_twd is not None and max_price_twd < 0):
            error_message = "價格必須是 0 或正數（或留空）。"
        elif max_price_twd is not None and min_price_twd > max_price_twd:
            error_message = "最低價格不能高於最高價格。"
        else:
            results = search_games(name_keyword, tag_keyword, min_price_twd, max_price_twd)
            return render_template(
                "index.html",
                games=all_games,
                tags=all_tags,
                results=results,
                error_message=error_message,
                form=form_values,
                searched=True,
            )

    return render_template(
        "index.html",
        games=all_games,
        tags=all_tags,
        results=[],
        error_message=error_message,
        form=form_values,
        searched=False,
    )


if __name__ == "__main__":
    app.run(debug=True)
