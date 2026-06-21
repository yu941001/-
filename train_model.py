import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import pickle
from pathlib import Path

# 讀取歷史資料
print("讀取歷史資料中...")
# 1. 讀取剛剛生成的歷史資料
base_dir = Path(__file__).resolve().parent
input_path = base_dir / 'historical_user_data.csv'
output_path = base_dir / 'recommendation_model.pkl'

df = pd.read_csv(input_path)

# 2. 分離特徵 (X) 與標籤 (y)
X = df.drop('Target_Product', axis=1)
y = df['Target_Product']

# 建立並訓練隨機森林模型
print("正在訓練隨機森林模型...")
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X, y)

# 4. 儲存模型與類別標籤，供 API 使用
with open(output_path, 'wb') as f:
    pickle.dump({
        'model': model,
        'classes': model.classes_
    }, f)

print(f"模型訓練完成，已成功儲存為 {output_path.name}")