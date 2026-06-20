import sqlite3
# 連接到你的資料庫
conn = sqlite3.connect('health_system.db')
cursor = conn.cursor()

# 查詢季節疾病表裡的所有資料
cursor.execute("SELECT * FROM seasonal_diseases;")
rows = cursor.fetchall()

print("=== 目前資料庫裡的季節疾病數據 ===")
for row in rows:
    print(f"月份: {row[1]}月 | 疾病: {row[2]} | 風險: {row[3]} | 來源: {row[4]}")

conn.close()