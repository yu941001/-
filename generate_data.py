import pandas as pd
import random
import os
from pathlib import Path

# 準備產生的資料筆數
NUM_SAMPLES = int(os.environ.get("NUM_SAMPLES", "5000"))

data = []
products = ["綜合維他命", "高濃度維他命C", "益生菌", "深海魚油", "葡萄糖胺", "B群", "葉黃素", "鈣D3", "薑黃素"]

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

    # 邏輯決策：用加權分數讓不同產品類別都能穩定出現
    product_scores = {product: random.randint(0, 2) for product in products}

    if cond_joint == 1 and age > 50:
        product_scores["葡萄糖胺"] += 8
    if cond_digestion == 1 or habit_eat_out == 1 or hist_enteric == 1:
        product_scores["益生菌"] += 8
    if cond_immunity == 1 or habit_stress == 1 or hist_flu == 1:
        product_scores["高濃度維他命C"] += 8
    if habit_stay_late == 1 and habit_stress == 1 and cond_fatigue == 0:
        product_scores["B群"] += 9
    if age >= 40 and habit_stay_late == 1:
        product_scores["葉黃素"] += 7
    if age >= 45 and habit_no_exercise == 1:
        product_scores["鈣D3"] += 7
    if habit_stay_late == 1 or cond_fatigue == 1 or hist_allergy == 1:
        product_scores["綜合維他命"] += 6
    if (habit_no_exercise == 1 and age > 30) or hist_cardio == 1:
        product_scores["深海魚油"] += 9
    if cond_joint == 1 or age > 35:
        product_scores["薑黃素"] += 6

    target = max(product_scores, key=product_scores.get)

    # 將這筆資料加入清單（必須嚴格對齊欄位順序）
    data.append([
        age, gender,
        habit_eat_out, habit_stay_late, habit_stress, habit_no_exercise,
        cond_fatigue, cond_immunity, cond_digestion, cond_joint,
        hist_flu, hist_enteric, hist_allergy, hist_cardio, # ✨ 補上新特徵
        target
    ])

# 轉換成 DataFrame 並儲存
columns = [
    'Age', 'Gender',
    'Habit_外食', 'Habit_熬夜', 'Habit_壓力大', 'Habit_少運動',
    'Cond_容易疲勞', 'Cond_免疫力低下', 'Cond_排便不順', 'Cond_關節不適',
    'Hist_流感感冒', 'Hist_腸病毒腹瀉', 'Hist_過敏紀錄', 'Hist_三高心血管', # ✨ 欄位名稱
    'Target_Product'
]

df = pd.DataFrame(data, columns=columns)
base_dir = Path(__file__).resolve().parent
output_path = base_dir / 'historical_user_data.csv'
df.to_csv(output_path, index=False, encoding='utf-8-sig')

print(f"🎉 成功生成包含歷史疾病特徵的模擬數據！共 {NUM_SAMPLES} 筆，已儲存至 {output_path.name}")