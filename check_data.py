import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'health_system.db'


def init_database():
    conn = sqlite3.connect(DB_PATH)
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
        cursor.execute('''
        INSERT OR IGNORE INTO products (name, min_age, target_habits, target_conditions)
        VALUES (?, ?, ?, ?);
        ''', prod)

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
            cursor.execute('''
            INSERT OR IGNORE INTO product_disease_mapping (product_id, disease_name)
            VALUES (?, ?);
            ''', (row[0], disease))

    conn.commit()
    conn.close()


def main():
    init_database()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM seasonal_diseases;")
    rows = cursor.fetchall()

    print("=== 目前資料庫裡的季節疾病資料 ===")
    for row in rows:
        print(f"月份: {row[1]}月 | 疾病: {row[2]} | 風險: {row[3]} | 來源: {row[4]}")

    conn.close()


if __name__ == '__main__':
    main()