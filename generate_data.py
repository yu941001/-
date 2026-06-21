import pandas as pd
import random
import os
import sqlite3
from pathlib import Path

# 準備產生的資料筆數
NUM_SAMPLES = int(os.environ.get("NUM_SAMPLES", "5000"))

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'health_system.db'


def load_product_profiles_from_db():
    """從資料庫讀取產品資料與疾病對應，不在程式中手寫產品清單。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT p.name, p.min_age, p.target_habits, p.target_conditions, m.disease_name
        FROM products p
        LEFT JOIN product_disease_mapping m ON p.id = m.product_id
        ORDER BY p.name;
    ''')

    profiles = {}
    for row in cursor.fetchall():
        product_name = row['name']
        if product_name not in profiles:
            raw_habits = row['target_habits'] or ''
            raw_conditions = row['target_conditions'] or ''
            profiles[product_name] = {
                'min_age': row['min_age'] or 0,
                'target_habits': [h.strip() for h in raw_habits.split(',') if h.strip()],
                'target_conditions': [c.strip() for c in raw_conditions.split(',') if c.strip()],
                'diseases': set()
            }
        if row['disease_name']:
            profiles[product_name]['diseases'].add(row['disease_name'])

    conn.close()

    if not profiles:
        raise RuntimeError(
            "資料庫中沒有任何 products 資料，無法建立訓練標籤。"
            "請先匯入產品資料再執行 generate_data.py。"
        )

    return profiles


product_profiles = load_product_profiles_from_db()
products = list(product_profiles.keys())
data = []

# 由歷史病史映射到疾病關鍵字，用於泛化匹配
history_to_keywords = {
    '流感': ['流感', '感冒', '呼吸道'],
    '腹瀉': ['腹瀉', '腸胃炎', '食物中毒', '諾羅'],
    '過敏': ['過敏', '鼻炎', '氣喘'],
    '心血管': ['心血管', '三高', '高血脂']
}

# 季節疾病特徵映射（對應爬蟲資料庫的疾病訊號）
season_feature_keywords = {
    'Season_流感': ['流感'],
    'Season_腸病毒': ['腸病毒'],
    'Season_登革熱': ['登革熱'],
    'Season_新冠肺炎': ['新冠', 'COVID'],
    'Season_諾羅病毒': ['諾羅']
}

for _ in range(NUM_SAMPLES):
    # 隨機生成使用者特徵
    age = random.randint(10, 80)
    gender = random.choice([0, 1]) # 0:女, 1:男
    
    # 隨機生活習慣 (0=無, 1=有)
    habit_eat_out = random.choice([0, 1])
    habit_stay_late = random.choice([0, 1])
    habit_stress = random.choice([0, 1])
    habit_no_exercise = random.choice([0, 1])
    
    # 隨機健康困擾 (0=無, 1=有)
    cond_fatigue = random.choice([0, 1])
    cond_immunity = random.choice([0, 1])
    cond_digestion = random.choice([0, 1])
    cond_joint = random.choice([0, 1])

    # ✨【新增】隨機歷史疾病紀錄 (0=無, 1=有)
    hist_flu = random.choice([0, 1])          # 過去曾患流感/重感冒
    hist_enteric = random.choice([0, 1])      # 過去曾患腸病毒/嚴重腹瀉
    hist_allergy = random.choice([0, 1])      # 過去有常態過敏紀錄
    hist_cardio = random.choice([0, 1])       # 過去有心血管/三高紀錄

    # 由爬蟲資料庫概念抽象出的「當月疾病風險特徵」(0=無, 1=有)
    season_flu = random.choice([0, 1])
    season_enterovirus = random.choice([0, 1])
    season_dengue = random.choice([0, 1])
    season_covid = random.choice([0, 1])
    season_norovirus = random.choice([0, 1])

    # 邏輯決策：從資料庫產品設定與疾病對應動態計分，不手寫產品規則
    product_scores = {product: random.randint(0, 2) for product in products}

    user_habits = []
    if habit_eat_out == 1:
        user_habits.append('外食')
    if habit_stay_late == 1:
        user_habits.append('熬夜')
    if habit_stress == 1:
        user_habits.append('壓力大')
    if habit_no_exercise == 1:
        user_habits.append('少運動')

    user_conditions = []
    if cond_fatigue == 1:
        user_conditions.append('容易疲勞')
    if cond_immunity == 1:
        user_conditions.append('免疫力低下')
    if cond_digestion == 1:
        user_conditions.append('排便不順')
    if cond_joint == 1:
        user_conditions.append('關節不適')

    user_history = []
    if hist_flu == 1:
        user_history.append('流感')
    if hist_enteric == 1:
        user_history.append('腹瀉')
    if hist_allergy == 1:
        user_history.append('過敏')
    if hist_cardio == 1:
        user_history.append('心血管')

    season_flags = {
        'Season_流感': season_flu,
        'Season_腸病毒': season_enterovirus,
        'Season_登革熱': season_dengue,
        'Season_新冠肺炎': season_covid,
        'Season_諾羅病毒': season_norovirus,
    }

    for product_name, profile in product_profiles.items():
        min_age = profile['min_age']
        target_habits = profile['target_habits']
        target_conditions = profile['target_conditions']
        disease_text = ' '.join(profile['diseases'])

        if age < min_age:
            product_scores[product_name] -= 6

        matched_habits = [h for h in user_habits if h in target_habits]
        product_scores[product_name] += len(matched_habits) * 4

        matched_conditions = [c for c in user_conditions if c in target_conditions]
        product_scores[product_name] += len(matched_conditions) * 5

        for h in user_history:
            keywords = history_to_keywords.get(h, [])
            if any(k in disease_text for k in keywords):
                product_scores[product_name] += 6

        for feature_name, enabled in season_flags.items():
            if enabled != 1:
                continue
            keywords = season_feature_keywords[feature_name]
            if any(k in disease_text for k in keywords):
                product_scores[product_name] += 8

    target = max(product_scores, key=product_scores.get)

    # 將這筆資料加入清單（必須嚴格對齊欄位順序）
    data.append([
        age, gender,
        habit_eat_out, habit_stay_late, habit_stress, habit_no_exercise,
        cond_fatigue, cond_immunity, cond_digestion, cond_joint,
        hist_flu, hist_enteric, hist_allergy, hist_cardio,
        season_flu, season_enterovirus, season_dengue, season_covid, season_norovirus,
        target
    ])

# 轉換成 DataFrame 並儲存
columns = [
    'Age', 'Gender',
    'Habit_外食', 'Habit_熬夜', 'Habit_壓力大', 'Habit_少運動',
    'Cond_容易疲勞', 'Cond_免疫力低下', 'Cond_排便不順', 'Cond_關節不適',
    'Hist_流感感冒', 'Hist_腸病毒腹瀉', 'Hist_過敏紀錄', 'Hist_三高心血管',
    'Season_流感', 'Season_腸病毒', 'Season_登革熱', 'Season_新冠肺炎', 'Season_諾羅病毒',
    'Target_Product'
]

df = pd.DataFrame(data, columns=columns)
output_path = BASE_DIR / 'historical_user_data.csv'
df.to_csv(output_path, index=False, encoding='utf-8-sig')

print(f"🎉 成功生成資料庫驅動的訓練數據！產品類別 {len(products)} 種，共 {NUM_SAMPLES} 筆，已儲存至 {output_path.name}")