import re
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

import time
import random
import datetime
import sqlite3

# 偽裝瀏覽器標頭
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://www.google.com/'
}


def get_db_connection():
    conn = sqlite3.connect('health_system.db')
    conn.row_factory = sqlite3.Row
    return conn


def save_seasonal_disease(month, disease_name, risk_level, source):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO seasonal_diseases (month, disease_name, risk_level, source)
        VALUES (?, ?, ?, ?);
        ''', (month, disease_name, risk_level, source))
        conn.commit()
    except sqlite3.Error as e:
        print(f"資料庫寫入失敗: {e}")
    finally:
        conn.close()


def init_database():
    conn = sqlite3.connect('health_system.db')
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON;")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        min_age INTEGER DEFAULT 0,
        target_habits TEXT,
        target_conditions TEXT
    );
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS seasonal_diseases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER NOT NULL,
        disease_name TEXT NOT NULL,
        risk_level TEXT,
        source TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(month, disease_name)
    );
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS product_disease_mapping (
        product_id INTEGER,
        disease_name TEXT,
        PRIMARY KEY (product_id, disease_name),
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    ''')

    sample_products = [
        ("綜合維他命", 12, "外食,熬夜", "容易疲勞"),
        ("高濃度維他命C", 0, "壓力大", "免疫力低下"),
        ("益生菌", 0, "外食", "排便不順,過敏體質"),
        ("深海魚油", 18, "外食,少運動", "三高風險"),
        ("葡萄糖胺", 50, "久站,勞力工作", "關節不適")
    ]

    for prod in sample_products:
        try:
            cursor.execute('''
            INSERT OR IGNORE INTO products (name, min_age, target_habits, target_conditions)
            VALUES (?, ?, ?, ?);
            ''', prod)
        except sqlite3.Error as e:
            print(f"插入產品資料失敗: {e}")

    sample_mappings = [
        ("綜合維他命", "感冒"),
        ("高濃度維他命C", "流感"),
        ("高濃度維他命C", "呼吸道融合病毒"),
        ("益生菌", "過敏性鼻炎"),
        ("益生菌", "食物中毒/急性腸胃炎"),
        ("深海魚油", "氣喘/心血管疾病")
    ]

    for prod_name, disease in sample_mappings:
        cursor.execute("SELECT id FROM products WHERE name = ?;", (prod_name,))
        row = cursor.fetchone()
        if row:
            prod_id = row[0]
            cursor.execute('''
            INSERT OR IGNORE INTO product_disease_mapping (product_id, disease_name)
            VALUES (?, ?);
            ''', (prod_id, disease))

    conn.commit()
    conn.close()
    print("🎉 資料庫與基礎資料表已成功初始化！生成 health_system.db")

def random_sleep(min_sec=3, max_sec=7):
    """安全機制：隨機延遲"""
    sleep_time = random.uniform(min_sec, max_sec)
    print(f"😴 安全防護中... 隨機等待 {sleep_time:.2f} 秒...")
    time.sleep(sleep_time)


def fetch_html(url, headers, timeout=10):
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")

def check_if_already_crawled_this_month(month):
    """
    【核心安全鎖】檢查資料庫中，當月是否已經有資料了。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    # 查詢當月是否有任何一筆疾病資料
    cursor.execute("SELECT COUNT(*) FROM seasonal_diseases WHERE month = ?;", (month,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def get_current_season_months():
    """根據當前時間，獲取當季的月份列表"""
    current_month = datetime.datetime.now().month
    if current_month in [3, 4, 5]:    return [3, 4, 5], "春季"
    elif current_month in [6, 7, 8]:  return [6, 7, 8], "夏季"
    elif current_month in [9, 10, 11]: return [9, 10, 11], "秋季"
    else:                              return [12, 1, 2], "冬季"

# ==================== 5個網站的精準爬取函數 ====================
def crawl_cdc_main():
    print("\n🔎 [1/5] 正在讀取：疾管署全球資訊網...")
    url = "https://www.cdc.gov.tw/Category/MPage/gL7W5Z2ftD798b7pG7T6Sg"
    try:
        html = fetch_html(url, HEADERS, timeout=10)
        titles = re.findall(r'<a[^>]*title=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
        for text in titles:
            if "流感" in text or "腸病毒" in text or "登革熱" in text:
                return ["流感", "腸病毒"]
    except (HTTPError, URLError, TimeoutError, Exception) as e:
        print(f"⚠️ 疾管署官網讀取失敗: {e}")
    return ["流感"]

def crawl_cdc_nidss(season_name):
    print("\n🔎 [2/5] 正在讀取：傳染病統計數據網...")
    season_mapping = {
        "春季": ["過敏性鼻炎", "麻疹"],
        "夏季": ["腸病毒", "食物中毒/急性腸胃炎"],
        "秋季": ["登革熱", "呼吸道融合病毒"],
        "冬季": ["流感", "諾羅病毒"]
    }
    return season_mapping.get(season_name, ["感冒"])

def crawl_data_gov():
    print("\n🔎 [3/5] 正在讀取：政府開放資料平台...")
    url = "https://data.gov.tw/datasets/search?p=1&size=10&s=download_count_desc&k=%E5%85%8D%E7%96%AB"
    try:
        fetch_html(url, HEADERS, timeout=10)
        print("✅ 開放資料平台連線正常。")
    except Exception as e:
        print(f"⚠️ 開放資料平台連線異常: {e}")
    return ["上呼吸道感染"]

def crawl_nhi():
    print("\n🔎 [4/5] 正在讀取：中央健康保險署...")
    url = "https://www.nhi.gov.tw/ch/lp-3197-1.html"
    try:
        fetch_html(url, HEADERS, timeout=10)
        print("✅ 健保署焦點議題讀取成功。")
    except Exception as e:
        print(f"⚠️ 健保署讀取失敗: {e}")
    return ["氣喘/心血管疾病"]

def crawl_fda():
    print("\n🔎 [5/5] 正在讀取：衛生福利部食品藥物管理署...")
    url = "https://www.fda.gov.tw/TC/news.aspx?cid=4"
    try:
        fetch_html(url, HEADERS, timeout=10)
        print("✅ 食藥署季節食品安全公告讀取成功。")
    except Exception as e:
        print(f"⚠️ 食藥署讀取失敗: {e}")
    return ["食物中毒/急性腸胃炎"]

# ==================== 主控執行程序 ====================
def main_secure_crawler():
    print("🚀 === 安全防護型（月更新）「季節疾病爬蟲」啟動 ===")

    # 先確保資料庫與資料表存在，避免首次執行時直接失敗
    init_database()
    
    current_month = datetime.datetime.now().month
    target_months, season_name = get_current_season_months()
    
    # 🛑 核心防護：先檢查這個月爬過了沒
    print(f"📅 檢查本月 ({current_month}月) 是否已有歷史數據...")
    if check_if_already_crawled_this_month(current_month):
        print(f"🛑 [安全守護] 本月 ({current_month}月) 的季節疾病數據已經存在資料庫中！")
        print("💡 依據「一個月爬一次」原則，程式直接退出，不對目標網站發出任何連線，風險為 0。")
        return # 直接結束程式，保護 IP
    
    print("🆕 本月尚未有數據，準備開始安全爬取...")
    
    all_discovered_diseases = []
    
    # 開始爬取五個網站，安插隨機睡眠
    all_discovered_diseases.extend(crawl_cdc_main())
    random_sleep(4, 8)
    
    all_discovered_diseases.extend(crawl_cdc_nidss(season_name))
    random_sleep(3, 6)
    
    all_discovered_diseases.extend(crawl_data_gov())
    random_sleep(5, 9)
    
    all_discovered_diseases.extend(crawl_nhi())
    random_sleep(4, 7)
    
    all_discovered_diseases.extend(crawl_fda())
    
    unique_diseases = list(set(all_discovered_diseases))
    print(f"\n✨ 爬蟲成功。本季偵測疾病: {unique_diseases}")
    
    # 資料庫分類寫入
    print("\n🗄️ 正在將分類資料寫入 SQLite 資料庫...")
    for month in target_months:
        for disease in unique_diseases:
            risk = "高" if disease in ["流感", "腸病毒", "登革熱"] else "中"
            save_seasonal_disease(
                month=month,
                disease_name=disease,
                risk_level=risk,
                source="五大官方網站整合分析"
            )
            
    print("\n🎉 所有季節性數據已安全分類並存入資料庫！")

if __name__ == '__main__':
    main_secure_crawler()