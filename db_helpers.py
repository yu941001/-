import sqlite3

def get_db_connection():
    conn = sqlite3.connect('health_system.db')
    conn.row_factory = sqlite3.Row # 讓查詢結果可以用欄位名稱讀取，例如 row['name']
    return conn

# 【給爬蟲用】儲存爬到的季節性疾病
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

# 【給 API 推薦邏輯用】根據月份撈出當季流行疾病
def get_diseases_by_month(month):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT disease_name FROM seasonal_diseases WHERE month = ?;
    ''', (month,))
    rows = cursor.fetchall()
    conn.close()
    return [row['disease_name'] for row in rows]

# 【給 API 推薦邏輯用】撈出所有保健食品及它們能預防的疾病
def get_all_products_with_diseases():
    conn = get_db_connection()
    cursor = conn.cursor()
    # 使用 LEFT JOIN 把產品和它對應的疾病連在一起
    cursor.execute('''
    SELECT p.id, p.name, p.min_age, p.target_habits, p.target_conditions, m.disease_name
    FROM products p
    LEFT JOIN product_disease_mapping m ON p.id = m.product_id;
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    # 整理成結構化的字典
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