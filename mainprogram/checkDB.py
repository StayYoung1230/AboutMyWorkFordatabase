# -*- coding: utf-8 -*-
"""
使用 fetchall() 顯示 mydb4final.db 中所有資料表內容
"""

import sqlite3

DB_NAME = "mydb4final.db"

TABLES = [
    "Game",
    "Developer",
    "Publisher",
    "Tag",
    "Region",
    "DeveloperGame",
    "PublisherGame",
    "GameTag",
    "PriceRecord"
]

def print_table(cur, table_name):
    print(f"\n====================================")
    print(f"   {table_name} 資料內容")
    print(f"====================================")

    # 抓欄位名稱
    cur.execute(f"PRAGMA table_info({table_name});")
    columns = [col[1] for col in cur.fetchall()]

    # 抓資料
    cur.execute(f"SELECT * FROM {table_name};")
    rows = cur.fetchall()

    # 印欄位名稱
    print(" | ".join(columns))
    print("-" * 60)

    # 印每一筆資料
    if not rows:
        print("(無資料)")
    else:
        for row in rows:
            row_str = " | ".join(str(x) if x is not None else "NULL" for x in row)
            print(row_str)
    
    # 印資料表的行數
    print(f"行數：{len(rows)}")




def main():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # 逐一印出所有資料表
    for table in TABLES:
        print_table(cur, table)

    conn.close()


if __name__ == "__main__":
    main()
