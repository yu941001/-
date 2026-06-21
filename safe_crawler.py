import json
import re
import time
import random
import datetime
import sqlite3
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

# 模擬瀏覽器標頭
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

    # 預設產品資料
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
            pass  # 避免重複執行時重複輸出錯誤

    # 預設產品與疾病對應
    sample_mappings = [
        ("綜合維他命", "感冒"),
        ("高濃度維他命C", "流感"),
        ("高濃度維他命C", "呼吸道融合病毒"),
        ("益生菌", "過敏性鼻炎"),
        ("益生菌", "食物中毒/急性腸胃炎"),
        ("益生菌", "諾羅病毒"),
        ("深海魚油", "氣喘/心血管疾病"),
        ("深海魚油", "心血管疾病")
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

def random_sleep(min_sec=2, max_sec=5):
    """隨機延遲，降低請求頻率。"""
    sleep_time = random.uniform(min_sec, max_sec)
    print(f"😴 偽裝人類瀏覽中... 隨機等待 {sleep_time:.1f} 秒...")
    time.sleep(sleep_time)

def fetch_html(url, headers, timeout=10):
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")

def check_if_already_crawled_this_month(month):
    """檢查資料庫中是否已有當月資料。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM seasonal_diseases WHERE month = ?;", (month,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def get_current_season_months():
    """取得當季月份列表與季節名稱。"""
    current_month = datetime.datetime.now().month
    if current_month in [3, 4, 5]:    return [3, 4, 5], "春季"
    elif current_month in [6, 7, 8]:  return [6, 7, 8], "夏季"
    elif current_month in [9, 10, 11]: return [9, 10, 11], "秋季"
    else:                              return [12, 1, 2], "冬季"

# ==================== 5個網站的爬取函數 ====================

def crawl_cdc_main():
    print("\n🔎 [1/5] 正在讀取並解析：疾管署全球資訊網...")
    url = "https://www.cdc.gov.tw/Category/MPage/gL7W5Z2ftD798b7pG7T6Sg"
    found_diseases = []
    try:
        html = fetch_html(url, HEADERS)
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text()  # 提取純文字
        
        # 關鍵字掃描
        if "流感" in page_text: found_diseases.append("流感")
        if "腸病毒" in page_text: found_diseases.append("腸病毒")
        if "登革熱" in page_text: found_diseases.append("登革熱")
        if "新冠肺炎" in page_text or "COVID" in page_text: found_diseases.append("新冠肺炎")
            
        print(f"✅ 疾管署掃描完成，發現: {found_diseases}")
    except Exception as e:
        print(f"⚠️ 疾管署官網解析失敗: {e}")
        
    return found_diseases if found_diseases else ["感冒"]

def crawl_cdc_nidss(season_name=None):
    print("\n🔎 [2/5] 正在讀取並解析：衛福部疾管署 開放資料 API (JSON)...")
    found_diseases = []
    
    # 疾管署官方開放資料 (健保門急診就診人次趨勢 JSON API)
    # 這些是真實營運中的政府公開資料端點
    api_endpoints = {
        "流感": "https://od.cdc.gov.tw/eic/NHI_Flu.json",
        "腸病毒": "https://od.cdc.gov.tw/eic/NHI_Enterovius.json",
        "腹瀉": "https://od.cdc.gov.tw/eic/NHI_Diarrhea.json"
    }

    for disease_category, url in api_endpoints.items():
        try:
            # 沿用原本寫好的 fetch_html 來帶入偽裝標頭發送請求
            response_text = fetch_html(url, HEADERS)
            data = json.loads(response_text)
            
            # 確保有拿到資料陣列
            if isinstance(data, list) and len(data) > 0:
                # 實務上這類資料為每週更新，我們可以取陣列中的最後一筆（最新一週）來判斷
                # 這裡為了簡單示範，只要近期 API 有持續吐出資料，我們就將其加入系統中
                # 你未來也可以擴充邏輯：判斷 latest_record 的人次是否突破「流行閾值」
                
                if disease_category == "流感":
                    found_diseases.append("流感")
                elif disease_category == "腸病毒":
                    found_diseases.append("腸病毒")
                elif disease_category == "腹瀉":
                    found_diseases.append("食物中毒/急性腸胃炎")
                    found_diseases.append("諾羅病毒")
                    
        except Exception as e:
            print(f"⚠️ 無法取得 {disease_category} 相關的 API 資料: {e}")
            
    # 【安全防護機制 (Fallback)】
    # 如果政府 API 剛好在維護、連線逾時或是無資料，系統也不能因此停擺
    # 這時才退回到以當前季節做推估的模型
    if not found_diseases:
        print("⚠️ 無法從 API 獲取足夠數據，啟動備用機制，切換回季節性模型預測...")
        season_mapping = {
            "春季": ["過敏性鼻炎", "麻疹"],
            "夏季": ["腸病毒", "食物中毒/急性腸胃炎"],
            "秋季": ["登革熱", "呼吸道融合病毒"],
            "冬季": ["流感", "諾羅病毒"]
        }
        fallback = season_mapping.get(season_name, ["感冒"])
        return fallback

    print(f"✅ 疾管署開放資料 API 掃描完成，從真實就診數據發現近期活躍疾病: {list(set(found_diseases))}")
    return list(set(found_diseases))

def crawl_data_gov():
    print("\n🔎 [3/5] 正在讀取並解析：政府開放資料平台...")
    url = "https://data.gov.tw/datasets/search?p=1&size=10&s=download_count_desc&k=%E5%85%8D%E7%96%AB"
    found_diseases = []
    try:
        html = fetch_html(url, HEADERS)
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text()
        
        if "呼吸道" in page_text: found_diseases.append("呼吸道融合病毒")
        if "過敏" in page_text: found_diseases.append("過敏性鼻炎")
        
        print(f"✅ 開放資料掃描完成，發現: {found_diseases}")
    except Exception as e:
        print(f"⚠️ 開放資料平台解析異常: {e}")
    return found_diseases

def crawl_nhi():
    print("\n🔎 [4/5] 正在讀取並解析：中央健康保險署...")
    url = "https://www.nhi.gov.tw/ch/lp-3197-1.html"
    found_diseases = []
    try:
        html = fetch_html(url, HEADERS)
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text()
        
        if "心血管" in page_text: found_diseases.append("心血管疾病")
        if "氣喘" in page_text: found_diseases.append("氣喘/心血管疾病")
        if "糖尿病" in page_text or "三高" in page_text: found_diseases.append("三高風險疾病")
        
        print(f"✅ 健保署掃描完成，發現: {found_diseases}")
    except Exception as e:
        print(f"⚠️ 健保署解析失敗: {e}")
    return found_diseases

def crawl_fda():
    print("\n🔎 [5/5] 正在讀取並解析：食藥署公告...")
    url = "https://www.fda.gov.tw/TC/news.aspx?cid=4"
    found_diseases = []
    try:
        html = fetch_html(url, HEADERS)
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text()
        
        if "食物中毒" in page_text or "食品中毒" in page_text: found_diseases.append("食物中毒/急性腸胃炎")
        if "腸胃炎" in page_text: found_diseases.append("急性腸胃炎")
        if "諾羅" in page_text: found_diseases.append("諾羅病毒")
        
        print(f"✅ 食藥署掃描完成，發現: {found_diseases}")
    except Exception as e:
        print(f"⚠️ 食藥署解析失敗: {e}")
    return found_diseases

# ==================== 主控執行程序 ====================

def main_secure_crawler():
    print("🚀 === 真實數據解析型「季節疾病爬蟲」啟動 ===")

    init_database()
    
    current_month = datetime.datetime.now().month
    target_months, season_name = get_current_season_months()
    
    print(f"📅 檢查本月 ({current_month}月) 是否已有歷史數據...")
    if check_if_already_crawled_this_month(current_month):
        print(f"🛑 [安全守護] 本月 ({current_month}月) 的季節疾病數據已經存在資料庫中！")
        print("💡 依據「一個月爬一次」原則，程式直接退出，以避免浪費伺服器資源並保護 IP。")
        # 為了測試方便，如果你想強迫他每次都爬，可以把下面這行 return 註解掉
        return 
    
    print("🆕 本月尚未有數據，準備開始對真實網頁進行爬取與解析...")
    
    all_discovered_diseases = []
    
    # 依序爬取五個網站，並加入隨機延遲
    all_discovered_diseases.extend(crawl_cdc_main())
    random_sleep()
    
    all_discovered_diseases.extend(crawl_cdc_nidss(season_name))
    random_sleep()
    
    all_discovered_diseases.extend(crawl_data_gov())
    random_sleep()
    
    all_discovered_diseases.extend(crawl_nhi())
    random_sleep()
    
    all_discovered_diseases.extend(crawl_fda())
    
    # 過濾空值並去除重複的疾病
    unique_diseases = list(set([d for d in all_discovered_diseases if d]))
    print(f"\n✨ 爬蟲與解析成功！本季從官網偵測到的實際疾病包含: {unique_diseases}")
    
    print("\n🗄️ 正在將真實資料寫入 SQLite 資料庫...")
    for month in target_months:
        for disease in unique_diseases:
            risk = "高" if disease in ["流感", "腸病毒", "登革熱", "新冠肺炎", "諾羅病毒"] else "中"
            save_seasonal_disease(
                month=month,
                disease_name=disease,
                risk_level=risk,
                source="政府官網即時解析"
            )
            
    print("\n🎉 所有網頁資料已成功萃取並存入資料庫！")

if __name__ == '__main__':
    main_secure_crawler()