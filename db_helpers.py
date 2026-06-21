import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'health_system.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# 儲存季節性疾病資料
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

# 依月份取得季節性疾病
def get_diseases_by_month(month):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT disease_name FROM seasonal_diseases WHERE month = ?;
    ''', (month,))
    rows = cursor.fetchall()
    conn.close()
    return [row['disease_name'] for row in rows]

# 取得所有保健食品與對應疾病
def get_all_products_with_diseases():
    conn = get_db_connection()
    cursor = conn.cursor()
    # 將產品與對應疾病一起取出
    cursor.execute('''
    SELECT p.id, p.name, p.min_age, p.target_habits, p.target_conditions, m.disease_name
    FROM products p
    LEFT JOIN product_disease_mapping m ON p.id = m.product_id;
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    # 整理成結構化資料
    products_dict = {}
    for row in rows:
        pid = row['id']
        if pid not in products_dict:
            products_dict[pid] = {
                "name": row['name'],
                "min_age": row['min_age'],
                "target_habits": row['target_habits'].split(',') if row['target_habits'] else [],
                "target_conditions": row['target_conditions'].split(',') if row['target_conditions'] else [],
                "prevent_diseases": []
            }
        if row['disease_name']:
            products_dict[pid]["prevent_diseases"].append(row['disease_name'])
            
    return list(products_dict.values())