import sqlite3
import json
import numpy as np
from pathlib import Path
from typing import Any, Tuple
from sklearn.ensemble import RandomForestRegressor
import pickle

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'health_system.db'
MODEL_PATH = BASE_DIR / 'recommendation_model.pkl'

# 規則引擎的別名與關鍵字定義（與 app.py 同步）
HABIT_ALIAS_MAP = {
    '久坐': ['少運動'],
    '睡眠不足': ['熬夜'],
    '飲食不規律': ['外食'],
}

CONDITION_ALIAS_MAP = {
    '過敏體質': ['免疫力低下'],
    '睡眠品質不佳': ['容易疲勞'],
    '消化不良': ['排便不順'],
    '體能不佳': ['容易疲勞'],
}

HISTORY_ALIAS_MAP = {
    '新冠肺炎': ['流感'],
    '腸病毒': ['腹瀉'],
    '諾羅病毒': ['腹瀉'],
    '登革熱': ['流感'],
    '骨質疏鬆': ['心血管'],
    '失眠': ['流感'],
}

EXTRA_HABIT_KEYWORDS = {
    '久坐': ['少運動', '關節', '心血管', '三高', '循環'],
    '睡眠不足': ['睡眠', '失眠', '疲勞', 'B群', '鎂'],
    '飲食不規律': ['外食', '消化', '腸胃', '益生菌', '消化酵素'],
}

EXTRA_CONDITION_KEYWORDS = {
    '過敏體質': ['過敏', '鼻炎', '氣喘', '益生菌'],
    '三高風險': ['心血管', '高血脂', '紅麴', '魚油', '輔酶Q10'],
    '睡眠品質不佳': ['失眠', '睡眠', '鎂', 'B群', '疲勞'],
}

EXTRA_HISTORY_KEYWORDS = {
    '新冠肺炎': ['新冠', '呼吸道', '流感', '免疫'],
    '失眠': ['失眠', '睡眠', '疲勞', '鎂', 'B群'],
}

HISTORY_TO_KEYWORDS = {
    '流感': ['流感', '感冒', '呼吸道'],
    '腹瀉': ['腹瀉', '腸胃炎', '食物中毒'],
    '過敏': ['過敏', '鼻炎', '氣喘'],
    '心血管': ['心血管', '高血脂', '三高'],
}

MIN_SCORE_THRESHOLD = 35
RULE_SCORE_CAP = 100


def expand_with_aliases(items, alias_map):
    expanded = set(items)
    for item in list(expanded):
        for alias in alias_map.get(item, []):
            expanded.add(alias)
    return list(expanded)


def build_product_search_text(prod_name, target_habits, target_conditions, preventable_diseases):
    habits_text = ' '.join(target_habits)
    conditions_text = ' '.join(target_conditions)
    disease_text = ' '.join(preventable_diseases)
    return f'{prod_name} {habits_text} {conditions_text} {disease_text}'


def calculate_rule_score(
    age: int,
    habits: list[str],
    conditions: list[str],
    history: list[str],
    current_diseases: list[str],
    product_name: str,
    target_habits: list[str],
    target_conditions: list[str],
    preventable_diseases: list[str],
    min_age: int,
) -> float:
    """用規則引擎計算產品推薦分數。"""
    if age < min_age:
        return 0.0

    rule_score = 0

    # 習慣匹配
    matched_habits = [h for h in habits if h in target_habits]
    if matched_habits:
        bonus = 8 + len(matched_habits) * 2
        rule_score += bonus

    # 困擾匹配
    matched_conditions = [c for c in conditions if c in target_conditions]
    if matched_conditions:
        bonus = 10 + len(matched_conditions) * 2
        rule_score += bonus

    # 病史關聯
    matched_history = []
    for h in history:
        keywords = HISTORY_TO_KEYWORDS.get(h, [])
        if any(any(k in disease for k in keywords) for disease in preventable_diseases):
            matched_history.append(h)

    if matched_history:
        rule_score += 20

    # 季節疾病命中
    for disease in preventable_diseases:
        if disease in current_diseases:
            rule_score += 25

    # 延伸習慣關聯
    product_search_text = build_product_search_text(product_name, target_habits, target_conditions, preventable_diseases)
    for item in habits:
        keywords = EXTRA_HABIT_KEYWORDS.get(item, [])
        hits = [k for k in keywords if k in product_search_text]
        if hits:
            bonus = 4 + min(4, len(hits))
            rule_score += bonus

    # 延伸困擾關聯
    for item in conditions:
        keywords = EXTRA_CONDITION_KEYWORDS.get(item, [])
        hits = [k for k in keywords if k in product_search_text]
        if hits:
            bonus = 4 + min(4, len(hits))
            rule_score += bonus

    return min(RULE_SCORE_CAP, rule_score)


def generate_synthetic_training_data(num_samples: int = 500) -> Tuple[np.ndarray, np.ndarray, list[str]]:
    """生成合成訓練數據。"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 讀取產品
    cursor.execute('SELECT name, min_age, target_habits, target_conditions FROM products;')
    products = []
    for row in cursor.fetchall():
        name, min_age, habits_str, conditions_str = row
        target_habits = [h.strip() for h in (habits_str or '').split(',') if h.strip()]
        target_conditions = [c.strip() for c in (conditions_str or '').split(',') if c.strip()]
        products.append({'name': name, 'min_age': min_age, 'target_habits': target_habits, 'target_conditions': target_conditions})

    # 讀取疾病映射
    cursor.execute('''
        SELECT p.name, m.disease_name
        FROM products p
        LEFT JOIN product_disease_mapping m ON p.id = m.product_id;
    ''')
    product_diseases = {}
    for prod_name, disease in cursor.fetchall():
        if prod_name not in product_diseases:
            product_diseases[prod_name] = []
        if disease:
            product_diseases[prod_name].append(disease)

    # 讀取季節疾病
    cursor.execute('SELECT DISTINCT disease_name FROM seasonal_diseases;')
    all_diseases = [row[0] for row in cursor.fetchall()]

    conn.close()

    if not products:
        print('ERROR: No products found in database.')
        return np.array([]), np.array([]), []

    # 定義可能的特徵值
    ages = list(range(18, 71, 5))  # 18-70 歲
    genders = ['男', '女']
    all_habits = list(HABIT_ALIAS_MAP.keys()) + ['健身', '運動量大', '喝水少', '勞力工作']
    all_conditions = list(CONDITION_ALIAS_MAP.keys()) + ['眼睛疲勞', '皮膚乾燥']
    all_history = list(HISTORY_TO_KEYWORDS.keys())

    X_data = []
    y_data = []
    product_names = [p['name'] for p in products]

    # 生成 num_samples 條合成樣本
    np.random.seed(42)
    for _ in range(num_samples):
        age = np.random.choice(ages)
        gender = np.random.choice(genders)
        
        # 隨機選擇 0-3 個習慣、困擾、病史
        num_habits = np.random.randint(0, 4)
        num_conditions = np.random.randint(0, 4)
        num_history = np.random.randint(0, 3)
        
        habits = list(np.random.choice(all_habits, size=num_habits, replace=False)) if num_habits > 0 else []
        conditions = list(np.random.choice(all_conditions, size=num_conditions, replace=False)) if num_conditions > 0 else []
        history = list(np.random.choice(all_history, size=num_history, replace=False)) if num_history > 0 else []
        
        # 隨機選擇當前季節疾病
        num_current_diseases = np.random.randint(1, 4)
        current_diseases = list(np.random.choice(all_diseases, size=num_current_diseases, replace=False)) if all_diseases else []

        # 正規化用戶輸入
        norm_habits = expand_with_aliases(habits, HABIT_ALIAS_MAP)
        norm_conditions = expand_with_aliases(conditions, CONDITION_ALIAS_MAP)
        norm_history = expand_with_aliases(history, HISTORY_ALIAS_MAP)

        # 為每個產品計算規則分數
        for product in products:
            preventable = product_diseases.get(product['name'], [])
            score = calculate_rule_score(
                age=age,
                habits=norm_habits,
                conditions=norm_conditions,
                history=norm_history,
                current_diseases=current_diseases,
                product_name=product['name'],
                target_habits=product['target_habits'],
                target_conditions=product['target_conditions'],
                preventable_diseases=preventable,
                min_age=product['min_age'],
            )

            # 特徵向量：age + gender_encoded + habits_vec + conditions_vec + history_vec + diseases_vec + score_label
            gender_encoded = 1 if gender == '男' else 0
            
            # 習慣多熱編碼
            habits_vec = [1 if h in norm_habits else 0 for h in all_habits]
            
            # 困擾多熱編碼
            conditions_vec = [1 if c in norm_conditions else 0 for c in all_conditions]
            
            # 病史多熱編碼
            history_vec = [1 if h in norm_history else 0 for h in all_history]
            
            # 季節疾病多熱編碼
            diseases_vec = [1 if d in current_diseases else 0 for d in all_diseases]

            feature_vector = [age, gender_encoded] + habits_vec + conditions_vec + history_vec + diseases_vec
            X_data.append(feature_vector)
            y_data.append(score)

    return np.array(X_data), np.array(y_data), product_names


def train_random_forest_model(X: np.ndarray, y: np.ndarray) -> RandomForestRegressor:
    """訓練隨機森林模型。"""
    print(f'Training Random Forest on {X.shape[0]} samples with {X.shape[1]} features...')
    
    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=15,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    
    model.fit(X, y)
    
    print(f'Model training complete. R² Score: {model.score(X, y):.4f}')
    
    return model


def save_model(model: RandomForestRegressor, X_shape: Tuple, product_names: list[str]):
    """保存模型和元信息。"""
    model_data = {
        'model': model,
        'feature_shape': X_shape,
        'product_names': product_names,
    }
    
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(model_data, f)
    
    print(f'Model saved to {MODEL_PATH}')


def main():
    print('🤖 === Random Forest Model Training ===')
    
    print('\nGenerating synthetic training data...')
    X, y, product_names = generate_synthetic_training_data(num_samples=500)
    
    if X.shape[0] == 0:
        print('ERROR: Failed to generate training data.')
        return
    
    print(f'✓ Generated {X.shape[0]} samples with {X.shape[1]} features')
    print(f'  Products: {len(product_names)}')
    
    print('\nTraining Random Forest model...')
    model = train_random_forest_model(X, y)
    
    print('\nSaving model...')
    save_model(model, X.shape, product_names)
    
    print('\n✓ Model training complete!')
    print(f'  Model file: {MODEL_PATH}')


if __name__ == '__main__':
    main()
