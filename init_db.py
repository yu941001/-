import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'health_system.db'

def init_database():
    # 建立或連接資料庫檔案
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 開啟外鍵限制
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 建立保健產品表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        min_age INTEGER DEFAULT 0,
        target_habits TEXT,
        target_conditions TEXT
    );
    ''')

    # 建立季節性疾病資料表
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

    # 建立產品與疾病對應表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS product_disease_mapping (
        product_id INTEGER,
        disease_name TEXT,
        PRIMARY KEY (product_id, disease_name),
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    ''')

    # 預填基礎保健食品資料
    sample_products = [
        ("綜合維他命", 12, "外食,熬夜", "容易疲勞"),
        ("高濃度維他命C", 0, "壓力大", "免疫力低下"),
        ("益生菌", 0, "外食", "排便不順,過敏體質"),
        ("深海魚油", 18, "外食,少運動", "三高風險"),
        ("葡萄糖胺", 50, "久站,勞力工作", "關節不適"),
        ("B群", 12, "熬夜,壓力大", "精神不濟"),
        ("葉黃素", 18, "長時間用眼,3C工作", "眼睛疲勞"),
        ("鈣D3", 40, "少曬太陽,少運動", "骨骼保養"),
        ("薑黃素", 30, "外食,久坐", "發炎體質")
    ]
    
    for prod in sample_products:
        try:
            cursor.execute('''
            INSERT OR IGNORE INTO products (name, min_age, target_habits, target_conditions)
            VALUES (?, ?, ?, ?);
            ''', prod)
        except sqlite3.Error as e:
            print(f"插入產品資料失敗: {e}")

    # 預填產品與疾病對應
    sample_mappings = [
        ("綜合維他命", "感冒"),
        ("高濃度維他命C", "流感"),
        ("高濃度維他命C", "呼吸道融合病毒"),
        ("益生菌", "過敏性鼻炎"),
        ("益生菌", "食物中毒/急性腸胃炎"),
        ("深海魚油", "氣喘/心血管疾病"),
        ("葡萄糖胺", "關節炎"),
        ("B群", "感冒"),
        ("葉黃素", "乾眼症"),
        ("鈣D3", "骨質疏鬆"),
        ("薑黃素", "發炎反應")
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