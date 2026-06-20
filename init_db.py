import sqlite3

def init_database():
    # 建立或連接到資料庫檔案
    conn = sqlite3.connect('health_system.db')
    cursor = conn.cursor()

    # 1. 開啟外鍵限制（確保資料關聯性）
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 2. 建立保健產品表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,          -- 產品名稱
        min_age INTEGER DEFAULT 0,         -- 最低適用年齡
        target_habits TEXT,                -- 適用生活習慣 (用逗號隔開，例如: 外食,熬夜)
        target_conditions TEXT             -- 適用健康狀況 (用逗號隔開，例如: 容易疲勞,排便不順)
    );
    ''')

    # 3. 建立季節性疾病歷史數據表 (爬蟲目標表)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS seasonal_diseases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER NOT NULL,            -- 月份 (1-12)
        disease_name TEXT NOT NULL,        -- 疾病名稱 (例如: 流感、腸病毒)
        risk_level TEXT,                   -- 風險等級 (高/中/低)
        source TEXT,                       -- 資料來源 (例如: 疾管署官網)
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(month, disease_name)        -- 避免同月份重複爬取相同疾病
    );
    ''')

    # 4. 建立產品與疾病的預防關聯表 (多對多)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS product_disease_mapping (
        product_id INTEGER,
        disease_name TEXT,
        PRIMARY KEY (product_id, disease_name),
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    ''')

    # ---- 預填一些基礎保健食品資料 (測試用) ----
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

    # ---- 預填產品與對應預防疾病的關聯 ----
    # 這裡的疾病名稱，之後要跟爬蟲抓下來的疾病名稱一致
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

    # 提交變更並關閉連線
    conn.commit()
    conn.close()
    print("🎉 資料庫與基礎資料表已成功初始化！生成 health_system.db")

if __name__ == '__main__':
    init_database()