import sqlite3
import numpy as np
from pathlib import Path
from typing import Any, Tuple
from sklearn.ensemble import RandomForestRegressor
from sklearn.multioutput import MultiOutputRegressor
import pickle

from config import (
    HABIT_ALIAS_MAP,
    CONDITION_ALIAS_MAP,
    HISTORY_ALIAS_MAP,
    MIN_SCORE_THRESHOLD,
    RULE_SCORE_CAP,
    DEFAULT_TRAINING_SAMPLES,
    REAL_DATA_TABLE_CANDIDATES,
    HISTORY_TO_KEYWORDS,
)
from utils import (
    expand_with_aliases,
    calculate_rule_score,
    parse_list_field,
    parse_product_scores_field,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'health_system.db'
MODEL_PATH = BASE_DIR / 'recommendation_model.pkl'


def load_real_training_data(
    product_names: list[str],
    all_habits: list[str],
    all_conditions: list[str],
    all_history: list[str],
    all_diseases: list[str],
) -> Tuple[np.ndarray, np.ndarray]:
    """讀取實際訓練資料；若不存在回傳空陣列。"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    existing_tables = {row[0] for row in cursor.fetchall()}

    selected_table = None
    required_columns = {
        'age',
        'gender',
        'habits',
        'conditions',
        'history',
        'current_diseases',
        'product_scores',
    }
    for table_name in REAL_DATA_TABLE_CANDIDATES:
        if table_name not in existing_tables:
            continue

        cursor.execute(f'PRAGMA table_info({table_name});')
        table_columns = {row[1] for row in cursor.fetchall()}
        if required_columns.issubset(table_columns):
            selected_table = table_name
            break

    if not selected_table:
        conn.close()
        return np.array([]), np.array([])

    cursor.execute(
        f'''SELECT age, gender, habits, conditions, history, current_diseases, product_scores
            FROM {selected_table}
            WHERE product_scores IS NOT NULL;'''
    )
    rows = cursor.fetchall()
    conn.close()

    X_real = []
    y_real = []

    for age, gender, habits_raw, conditions_raw, history_raw, diseases_raw, product_scores_raw in rows:
        try:
            age_int = int(age)
        except (TypeError, ValueError):
            continue

        gender_encoded = 1 if str(gender).strip() == '男' else 0
        habits = expand_with_aliases(parse_list_field(habits_raw), HABIT_ALIAS_MAP)
        conditions = expand_with_aliases(parse_list_field(conditions_raw), CONDITION_ALIAS_MAP)
        history = expand_with_aliases(parse_list_field(history_raw), HISTORY_ALIAS_MAP)
        current_diseases = parse_list_field(diseases_raw)
        score_map = parse_product_scores_field(product_scores_raw)

        if not score_map:
            continue

        habits_vec = [1 if h in habits else 0 for h in all_habits]
        conditions_vec = [1 if c in conditions else 0 for c in all_conditions]
        history_vec = [1 if h in history else 0 for h in all_history]
        diseases_vec = [1 if d in current_diseases else 0 for d in all_diseases]

        feature_vector = [age_int, gender_encoded] + habits_vec + conditions_vec + history_vec + diseases_vec
        product_vector = [float(score_map.get(prod_name, 0.0)) for prod_name in product_names]

        X_real.append(feature_vector)
        y_real.append(product_vector)

    if not X_real:
        return np.array([]), np.array([])

    return np.array(X_real), np.array(y_real)


def generate_synthetic_training_data(num_samples: int = DEFAULT_TRAINING_SAMPLES) -> Tuple[np.ndarray, np.ndarray, list[str]]:
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

        # 構建特徵向量（每個樣本一次）
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
        
        # 為每個產品計算規則分數，得到一個向量
        product_scores = []
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
            product_scores.append(score)
        
        y_data.append(product_scores)

    return np.array(X_data), np.array(y_data), product_names


def train_random_forest_model(X: np.ndarray, y: np.ndarray) -> MultiOutputRegressor:
    """訓練隨機森林模型以預測多個產品的分數。"""
    print(f'Training Random Forest on {X.shape[0]} samples with {X.shape[1]} features...')
    print(f'Output shape: {len(y[0]) if len(y) > 0 else 0} products')
    
    base_model = RandomForestRegressor(
        n_estimators=100,
        max_depth=15,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    
    model = MultiOutputRegressor(base_model)
    model.fit(X, y)
    
    print(f'Model training complete. R2 Score: {model.score(X, y):.4f}')
    
    return model


def save_model(model: MultiOutputRegressor, X_shape: Tuple, product_names: list[str], feature_metadata: dict):
    """保存模型和元信息。"""
    model_data = {
        'model': model,
        'feature_shape': X_shape,
        'product_names': product_names,
        'feature_metadata': feature_metadata,
    }
    
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(model_data, f)
    
    print(f'Model saved to {MODEL_PATH}')


def main():
    print('=== Random Forest Model Training ===')

    # 先建立固定特徵字典，確保模擬資料與實際資料共用相同特徵順序
    all_habits = list(HABIT_ALIAS_MAP.keys()) + ['健身', '運動量大', '喝水少', '勞力工作']
    all_conditions = list(CONDITION_ALIAS_MAP.keys()) + ['眼睛疲勞', '皮膚乾燥']
    all_history = list(HISTORY_TO_KEYWORDS.keys())

    print(f'\nGenerating synthetic training data ({DEFAULT_TRAINING_SAMPLES} samples)...')
    X_synth, y_synth, product_names = generate_synthetic_training_data(num_samples=DEFAULT_TRAINING_SAMPLES)

    if X_synth.shape[0] == 0:
        print('ERROR: Failed to generate synthetic training data.')
        return

    # 讀取季節疾病維度，供實際資料特徵向量使用
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT disease_name FROM seasonal_diseases;')
    all_diseases = [row[0] for row in cursor.fetchall()]
    conn.close()

    print('Loading real training data (if available)...')
    X_real, y_real = load_real_training_data(
        product_names=product_names,
        all_habits=all_habits,
        all_conditions=all_conditions,
        all_history=all_history,
        all_diseases=all_diseases,
    )

    X = X_synth.copy()
    y = y_synth.copy()

    real_count = int(X_real.shape[0]) if X_real.size > 0 else 0
    if real_count > 0:
        replace_count = min(real_count, X.shape[0])
        X[:replace_count] = X_real[:replace_count]
        y[:replace_count] = y_real[:replace_count]
        print(f'Applied {replace_count} real samples to override synthetic samples.')
    else:
        print('No real training data found. Using synthetic data only.')
    
    print(f'Generated {X.shape[0]} samples with {X.shape[1]} features')
    print(f'  Products: {len(product_names)}')
    
    # 建立特徵元資訊（供 app.py 使用）
    feature_metadata = {
        'all_habits': sorted(all_habits),
        'all_conditions': sorted(all_conditions),
        'all_history': sorted(all_history),
    }
    
    print('\nTraining Random Forest model...')
    model = train_random_forest_model(X, y)
    
    print('\nSaving model...')
    save_model(model, X.shape, product_names, feature_metadata)
    
    print('\nModel training complete!')
    print(f'  Model file: {MODEL_PATH}')


if __name__ == '__main__':
    main()
