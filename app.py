import json
import sqlite3
import datetime
import os
import socket
import pickle
import numpy as np
import subprocess
import atexit
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

MIN_RECOMMENDATIONS = 3
MIN_SCORE_THRESHOLD = 35
RULE_SCORE_CAP = 100

BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / 'index.html'
DB_PATH = BASE_DIR / 'health_system.db'
MODEL_PATH = BASE_DIR / 'recommendation_model.pkl'
LOCK_FILE = BASE_DIR / 'app.pid'

LLM_MODEL_NAME = os.environ.get('LLM_MODEL', 'gpt-4.1-mini')
llm_client = None
llm_enabled = False

rf_model = None
rf_enabled = False
rf_feature_shape = None
rf_product_names = []
rf_feature_metadata = None

INFECTIOUS_INCLUDE_KEYWORDS = {
    '流感', '腸病毒', '諾羅', '新冠', 'covid', '呼吸道融合', 'rsv',
    '登革熱', '麻疹', '百日咳', '肺炎', '病毒', '傳染'
}
INFECTIOUS_EXCLUDE_KEYWORDS = {
    '心血管', '三高', '高血脂', '高血壓', '糖尿病', '骨質疏鬆', '關節',
    '食物中毒', '急性腸胃炎'
}

# ==================== PID Lock 機制 ====================
def cleanup_old_process():
    """檢查舊 lock 檔案，如果有舊進程在監聽 port 5000，則殺掉它"""
    if not LOCK_FILE.exists():
        return
    
    try:
        with open(LOCK_FILE, 'r') as f:
            old_pid = int(f.read().strip())
        
        # 用 netstat 檢查是否有其他進程在 port 5000 上
        try:
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                timeout=5
            )
            lines = result.stdout.split('\n')
            for line in lines:
                if ':5000' in line and 'LISTENING' in line:
                    parts = line.split()
                    if parts:
                        pid_str = parts[-1]
                        try:
                            pid = int(pid_str)
                            if pid != os.getpid():  # 不要殺自己
                                print(f"🔍 偵測到舊進程 PID {pid} 還在監聽 port 5000，正在清理...")
                                subprocess.run(['taskkill', '/PID', str(pid), '/F'], 
                                             capture_output=True, timeout=5)
                                print(f"✅ 舊進程 PID {pid} 已清理")
                        except (ValueError, subprocess.TimeoutExpired, Exception) as e:
                            pass
        except Exception as e:
            print(f"⚠️  netstat 檢查失敗: {e}")
    except Exception as e:
        print(f"⚠️  讀取 lock 檔案失敗: {e}")


def acquire_lock():
    """寫入當前 PID 到 lock 檔案"""
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        print(f"🔐 PID Lock 已獲得 (PID: {os.getpid()})")
    except Exception as e:
        print(f"❌ 無法寫入 lock 檔案: {e}")


def release_lock():
    """刪除 lock 檔案"""
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
            print(f"🔓 PID Lock 已釋放")
    except Exception as e:
        print(f"⚠️  無法刪除 lock 檔案: {e}")


def is_recent_infectious_disease(disease_name: str) -> bool:
    if not disease_name:
        return False

    normalized = disease_name.strip().lower()
    if not normalized:
        return False

    if any(keyword in normalized for keyword in INFECTIOUS_EXCLUDE_KEYWORDS):
        return False

    return any(keyword in normalized for keyword in INFECTIOUS_INCLUDE_KEYWORDS)


class RecommendationItem(BaseModel):
    product_name: str
    final_score: int = Field(ge=0, le=100)
    ai_confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    analysis_summary: str


class RecommendationPayload(BaseModel):
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    strategy_summary: str = ''


def init_llm_client():
    global llm_client, llm_enabled
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        llm_enabled = False
        llm_client = None
        return

    base_url = os.environ.get('OPENAI_BASE_URL', '').strip() or None
    try:
        llm_client = OpenAI(api_key=api_key, base_url=base_url)
        llm_enabled = True
        print(f'✓ LLM enabled: {LLM_MODEL_NAME}')
    except Exception as exc:
        llm_enabled = False
        llm_client = None


def init_rf_model():
    global rf_model, rf_enabled, rf_feature_shape, rf_product_names, rf_feature_metadata
    
    if not MODEL_PATH.exists():
        print(f'WARNING: Random Forest model not found at {MODEL_PATH}')
        rf_enabled = False
        return
    
    try:
        with open(MODEL_PATH, 'rb') as f:
            model_data = pickle.load(f)
        
        rf_model = model_data.get('model')
        rf_feature_shape = model_data.get('feature_shape')
        rf_product_names = model_data.get('product_names', [])
        rf_feature_metadata = model_data.get('feature_metadata')
        
        if rf_model is not None:
            rf_enabled = True
            print(f'✓ Random Forest model loaded successfully')
        else:
            print(f'WARNING: Random Forest model file is corrupted or empty')
            rf_enabled = False
    except Exception as exc:
        print(f'WARNING: Failed to load Random Forest model: {exc}')
        rf_enabled = False


def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('PRAGMA foreign_keys = ON;')

    cursor.execute(
        '''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        min_age INTEGER DEFAULT 0,
        target_habits TEXT,
        target_conditions TEXT
    );
    '''
    )

    cursor.execute(
        '''
    CREATE TABLE IF NOT EXISTS seasonal_diseases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER NOT NULL,
        disease_name TEXT NOT NULL,
        risk_level TEXT,
        source TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(month, disease_name)
    );
    '''
    )

    cursor.execute(
        '''
    CREATE TABLE IF NOT EXISTS product_disease_mapping (
        product_id INTEGER,
        disease_name TEXT,
        PRIMARY KEY (product_id, disease_name),
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    '''
    )

    conn.commit()
    conn.close()


def ensure_database_ready():
    init_database()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))
        return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        sock.close()


def build_season_feature_map(current_diseases):
    joined = ' '.join(current_diseases)
    return {
        'Season_流感': 1 if '流感' in joined else 0,
        'Season_腸病毒': 1 if '腸病毒' in joined else 0,
        'Season_登革熱': 1 if '登革熱' in joined else 0,
        'Season_新冠肺炎': 1 if ('新冠肺炎' in joined or 'COVID' in joined) else 0,
        'Season_諾羅病毒': 1 if '諾羅' in joined else 0,
    }


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
    '健身': ['蛋白', '肌肉', '體能'],
    '運動量大': ['電解質', '蛋白', '體能', '鎂'],
    '喝水少': ['泌尿', '膳食纖維', '益生菌', '消化'],
    '勞力工作': ['關節', '葡萄糖胺', '鎂', '體能'],
}

EXTRA_CONDITION_KEYWORDS = {
    '過敏體質': ['過敏', '鼻炎', '氣喘', '益生菌'],
    '三高風險': ['心血管', '高血脂', '紅麴', '魚油', '輔酶Q10'],
    '睡眠品質不佳': ['失眠', '睡眠', '鎂', 'B群', '疲勞'],
    '消化不良': ['消化', '腸胃', '消化酵素', '益生菌', '膳食纖維'],
    '體能不佳': ['體能', '蛋白', 'B群', '輔酶Q10', '電解質'],
    '眼睛疲勞': ['眼睛', '葉黃素', '乾眼'],
    '皮膚乾燥': ['皮膚', '膠原蛋白', '維他命E', '抗氧化'],
}

EXTRA_HISTORY_KEYWORDS = {
    '新冠肺炎': ['新冠', '呼吸道', '流感', '免疫'],
    '失眠': ['失眠', '睡眠', '疲勞', '鎂', 'B群'],
    '腸病毒': ['腸病毒', '腸胃', '腹瀉', '益生菌'],
    '諾羅病毒': ['諾羅', '腸胃', '腹瀉', '益生菌'],
    '登革熱': ['登革熱', '流感', '免疫'],
    '骨質疏鬆': ['骨質', '鈣D3', '關節', '葡萄糖胺'],
}


def expand_with_aliases(items, alias_map):
    expanded = set(items)
    for item in list(expanded):
        for alias in alias_map.get(item, []):
            expanded.add(alias)
    return sorted(expanded)


def normalize_user_inputs(habits, conditions, history):
    norm_habits = expand_with_aliases(habits, HABIT_ALIAS_MAP)
    norm_conditions = expand_with_aliases(conditions, CONDITION_ALIAS_MAP)
    norm_history = expand_with_aliases(history, HISTORY_ALIAS_MAP)
    return norm_habits, norm_conditions, norm_history


def build_product_search_text(prod_name, profile, preventable):
    habits_text = ' '.join(profile.get('target_habits', []))
    conditions_text = ' '.join(profile.get('target_conditions', []))
    disease_text = ' '.join(preventable)
    return f'{prod_name} {habits_text} {conditions_text} {disease_text}'


def score_extra_options(raw_items, keyword_map, search_text, reason_prefix, summary_prefix):
    score = 0
    reasons = []
    summaries = []

    for item in raw_items:
        keywords = keyword_map.get(item, [])
        hits = [k for k in keywords if k in search_text]
        if not hits:
            continue

        bonus = 4 + min(4, len(hits))
        score += bonus
        reasons.append(f'{reason_prefix}：{item}（+{bonus}）')
        summaries.append(f'{summary_prefix}「{item}」與產品特性關聯，提升推薦指數')

    return min(score, 30), reasons, summaries


def build_rule_based_candidates(
    age: int,
    raw_habits: list[str],
    raw_conditions: list[str],
    raw_history: list[str],
    habits: list[str],
    conditions: list[str],
    history: list[str],
    current_diseases: list[str],
    season_feature_map: dict[str, int],
    product_profile_map: dict[str, dict[str, Any]],
    product_disease_map: dict[str, list[str]],
):
    history_to_keywords = {
        '流感': ['流感', '感冒', '呼吸道'],
        '腹瀉': ['腹瀉', '腸胃炎', '食物中毒'],
        '過敏': ['過敏', '鼻炎', '氣喘'],
        '心血管': ['心血管', '高血脂', '三高'],
    }

    candidate_products = []
    for prod_name, profile in product_profile_map.items():
        min_age = profile['min_age']
        target_habits = profile['target_habits']
        target_conditions = profile['target_conditions']
        preventable = product_disease_map.get(prod_name, [])
        product_search_text = build_product_search_text(prod_name, profile, preventable)

        if age < min_age:
            continue

        rule_score = 0
        matching_reasons = ['🧮 規則評分模式（LLM 不可用）']
        summary_parts = []

        active_season_signals = [name.replace('Season_', '') for name, val in season_feature_map.items() if val == 1]
        if active_season_signals:
            matching_reasons.append(f"🌡️ 納入當月疾病訊號：{'、'.join(active_season_signals)}")

        matched_habits = [h for h in habits if h in target_habits]
        if matched_habits:
            bonus = 8 + len(matched_habits) * 2
            rule_score += bonus
            matched_text = '、'.join(matched_habits)
            matching_reasons.append(f'🧩 習慣匹配：{matched_text}')
            summary_parts.append(f'生活習慣「{matched_text}」符合產品建議情境')

        matched_conditions = [c for c in conditions if c in target_conditions]
        if matched_conditions:
            bonus = 10 + len(matched_conditions) * 2
            rule_score += bonus
            matched_text = '、'.join(matched_conditions)
            matching_reasons.append(f'💡 困擾匹配：{matched_text}')
            summary_parts.append(f'健康困擾「{matched_text}」與產品定位一致')

        matched_history = []
        for h in history:
            keywords = history_to_keywords.get(h, [])
            if any(any(k in disease for k in keywords) for disease in preventable):
                matched_history.append(h)

        if matched_history:
            rule_score += 20
            matched_text = '、'.join(matched_history)
            matching_reasons.append(f'🛡️ 病史關聯：{matched_text}')

        for disease in preventable:
            if disease in current_diseases:
                rule_score += 25
                matching_reasons.append(f'🌍 季節防護命中：{disease}')

        habit_bonus, habit_reasons, habit_summaries = score_extra_options(
            raw_habits,
            EXTRA_HABIT_KEYWORDS,
            product_search_text,
            '🧭 延伸習慣關聯',
            '生活習慣',
        )
        if habit_bonus > 0:
            rule_score += habit_bonus
            matching_reasons.extend(habit_reasons)
            summary_parts.extend(habit_summaries)

        condition_bonus, condition_reasons, condition_summaries = score_extra_options(
            raw_conditions,
            EXTRA_CONDITION_KEYWORDS,
            product_search_text,
            '🩺 延伸困擾關聯',
            '健康困擾',
        )
        if condition_bonus > 0:
            rule_score += condition_bonus
            matching_reasons.extend(condition_reasons)
            summary_parts.extend(condition_summaries)

        history_bonus, history_reasons, history_summaries = score_extra_options(
            raw_history,
            EXTRA_HISTORY_KEYWORDS,
            product_search_text,
            '📚 延伸病史關聯',
            '歷史紀錄',
        )
        if history_bonus > 0:
            rule_score += history_bonus
            matching_reasons.extend(history_reasons)
            summary_parts.extend(history_summaries)

        final_score = min(RULE_SCORE_CAP, rule_score)
        if final_score < MIN_SCORE_THRESHOLD:
            continue

        if min_age > 0:
            summary_parts.append(f'年齡 {age} 歲已達建議使用年齡 {min_age} 歲')

        analysis_summary = '；'.join(summary_parts) + '。' if summary_parts else '主要根據你的填答特徵與資料庫規則進行推薦。'

        candidate_products.append(
            {
                'product_name': prod_name,
                'final_score': final_score,
                'ai_confidence': round(final_score / 100, 2),
                'reasons': matching_reasons,
                'analysis_summary': analysis_summary,
            }
        )

    candidate_products.sort(key=lambda x: x['final_score'], reverse=True)
    return candidate_products


def call_rf_recommendation(
    age: int,
    gender: str,
    raw_habits: list[str],
    raw_conditions: list[str],
    raw_history: list[str],
    normalized_habits: list[str],
    normalized_conditions: list[str],
    normalized_history: list[str],
    current_diseases: list[str],
    product_profile_map: dict[str, dict[str, Any]],
    product_disease_map: dict[str, list[str]],
):
    """用隨機森林模型進行推薦。"""
    if not rf_enabled or rf_model is None or not rf_feature_shape or not rf_feature_metadata:
        return []

    try:
        # 使用模型中保存的特徵列表（確保與訓練時一致）
        all_habits = rf_feature_metadata.get('all_habits', [])
        all_conditions = rf_feature_metadata.get('all_conditions', [])
        all_history = rf_feature_metadata.get('all_history', [])
        
        # 需要從資料庫獲取季節疾病列表（因為此列表在訓練時動態生成）
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT disease_name FROM seasonal_diseases;')
        all_diseases = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        # 構建特徵向量（與 train_model.py 同步）
        gender_encoded = 1 if gender == '男' else 0
        habits_vec = [1 if h in normalized_habits else 0 for h in all_habits]
        conditions_vec = [1 if c in normalized_conditions else 0 for c in all_conditions]
        history_vec = [1 if h in normalized_history else 0 for h in all_history]
        diseases_vec = [1 if d in current_diseases else 0 for d in all_diseases]

        feature_vector = np.array([[age, gender_encoded] + habits_vec + conditions_vec + history_vec + diseases_vec])

        # 用模型預測所有產品的分數（MultiOutputRegressor 返回 (1, num_products) 的數組）
        predictions = rf_model.predict(feature_vector)[0]

        results = []
        product_names_list = list(product_profile_map.keys())
        
        for idx, product_name in enumerate(product_names_list):
            if idx >= len(predictions):
                break
            
            score = float(predictions[idx])
            if score < MIN_SCORE_THRESHOLD:
                continue

            min_age = product_profile_map[product_name].get('min_age', 0)
            if age < min_age:
                continue

            target_habits = product_profile_map[product_name].get('target_habits', [])
            target_conditions = product_profile_map[product_name].get('target_conditions', [])
            preventable_diseases = product_disease_map.get(product_name, [])

            matched_habits = [h for h in normalized_habits if h in target_habits]
            matched_conditions = [c for c in normalized_conditions if c in target_conditions]
            matched_history = [
                h for h in normalized_history
                if any((h in d) or (d in h) for d in preventable_diseases)
            ]

            reason_parts = []
            if matched_habits:
                reason_parts.append(f"生活習慣符合：{'、'.join(matched_habits)}")
            if matched_conditions:
                reason_parts.append(f"健康困擾符合：{'、'.join(matched_conditions)}")
            if matched_history:
                reason_parts.append(f"病史關聯：{'、'.join(matched_history)}")

            analysis_summary = (
                '；'.join(reason_parts) + '。'
                if reason_parts
                else '根據你的年齡、生活習慣、健康困擾與病史特徵綜合評估後推薦此產品。'
            )

            results.append({
                'product_name': product_name,
                'final_score': int(min(100, max(0, score))),
                'ai_confidence': round(score / 100, 2),
                'reasons': ['🌳 Random Forest 模型評估'],
                'analysis_summary': analysis_summary,
                'raw_score': round(score, 1),
                'score_method': 'Random Forest 基於特徵向量（年齡、性別、習慣、困擾、病史、季節疾病）預測評分 → 年齡篩選（使用者年齡 ≥ 產品建議年齡）→ 門檻過濾（分數 ≥ 35）→ 限制區間（0-100）。',
                'min_age': min_age if min_age > 0 else None,
            })

        results.sort(key=lambda x: x['final_score'], reverse=True)
        return results[:6]

    except Exception as exc:
        print(f'WARNING: Random Forest prediction failed: {exc}')
        import traceback
        traceback.print_exc()
        return []


def call_llm_recommendation(
    age: int,
    gender: str,
    raw_habits: list[str],
    raw_conditions: list[str],
    raw_history: list[str],
    normalized_habits: list[str],
    normalized_conditions: list[str],
    normalized_history: list[str],
    current_diseases: list[str],
    seasonal_data_freshness: dict[str, Any],
    product_profile_map: dict[str, dict[str, Any]],
    product_disease_map: dict[str, list[str]],
):
    if not llm_enabled or llm_client is None:
        return []

    products = []
    for product_name, profile in product_profile_map.items():
        products.append(
            {
                'name': product_name,
                'min_age': profile.get('min_age', 0),
                'target_habits': profile.get('target_habits', []),
                'target_conditions': profile.get('target_conditions', []),
                'preventable_diseases': product_disease_map.get(product_name, []),
            }
        )

    if not products:
        return []

    prompt_payload = {
        'user': {
            'age': age,
            'gender': gender,
            'habits_raw': raw_habits,
            'conditions_raw': raw_conditions,
            'history_raw': raw_history,
            'habits_normalized': normalized_habits,
            'conditions_normalized': normalized_conditions,
            'history_normalized': normalized_history,
        },
        'environment': {
            'detected_seasonal_diseases': current_diseases,
            'seasonal_data_freshness': seasonal_data_freshness,
        },
        'products': products,
    }

    system_prompt = (
        '你是健康保健產品推薦分析助手。'
        '請只根據輸入資料做保守且可解釋的推薦，不要虛構產品。'
        '你必須輸出 JSON 物件，且僅包含 recommendations 與 strategy_summary 兩個欄位。'
        'recommendations 每筆都必須包含 product_name, final_score(0-100), ai_confidence(0-1), reasons, analysis_summary。'
        '只可推薦 products.name 中存在的產品，年齡未達 min_age 不可推薦。'
        '至少回傳 3 筆，最多回傳 6 筆，並依 final_score 由高到低排序。'
    )

    user_prompt = (
        '請根據以下 JSON 進行推薦，僅輸出 JSON：\n'
        + json.dumps(prompt_payload, ensure_ascii=False)
    )

    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            temperature=0.2,
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
        )
        content = response.choices[0].message.content or '{}'
        parsed = RecommendationPayload.model_validate(json.loads(content))
    except (ValidationError, ValueError, IndexError, KeyError) as exc:
        print(f'WARNING: LLM output parse failed: {exc}')
        return []
    except Exception as exc:
        print(f'WARNING: LLM call failed: {exc}')
        return []

    available = set(product_profile_map.keys())
    dedup = set()
    results = []

    for item in parsed.recommendations:
        product_name = item.product_name.strip()
        if product_name not in available:
            continue
        if product_name in dedup:
            continue
        min_age = product_profile_map.get(product_name, {}).get('min_age', 0)
        if age < min_age:
            continue

        dedup.add(product_name)
        results.append(
            {
                'product_name': product_name,
                'final_score': item.final_score,
                'ai_confidence': item.ai_confidence,
                'reasons': item.reasons or ['🤖 LLM 綜合評估'],
                'analysis_summary': item.analysis_summary,
            }
        )

    results.sort(key=lambda x: x['final_score'], reverse=True)
    return results[:6]


class RecommendationAPIHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _set_html_headers(self, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            if INDEX_FILE.exists():
                self._set_html_headers()
                self.wfile.write(INDEX_FILE.read_text(encoding='utf-8').encode('utf-8'))
            else:
                self._set_html_headers(404)
                self.wfile.write('找不到 index.html'.encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def do_HEAD(self):
        if self.path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            return

        if self.path == '/api/recommend':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        if self.path == '/api/recommend':
            try:
                content_length = int(self.headers.get('Content-Length', '0'))
                post_data = self.rfile.read(content_length)
                user_input = json.loads(post_data.decode('utf-8'))

                user_age = int(user_input.get('age', 0))
                user_gender = user_input.get('gender', '男')
                user_habits = user_input.get('habits', [])
                user_conditions = user_input.get('conditions', [])
                user_history = user_input.get('history', [])

                recommend_results = self.calculate_recommendations(
                    user_age, user_gender, user_habits, user_conditions, user_history
                )
                self._send_json(200, recommend_results)
            except Exception as exc:
                self._send_json(500, {'error': str(exc), 'message': '後端推薦計算失敗'})
        else:
            self._send_json(404, {'error': 'not found'})

    def calculate_recommendations(self, age, gender, habits, conditions, history):
        current_month = datetime.datetime.now().month
        recent_window_days = 30

        raw_habits = list(habits)
        raw_conditions = list(conditions)
        raw_history = list(history)
        habits, conditions, history = normalize_user_inputs(habits, conditions, history)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT disease_name, updated_at
            FROM seasonal_diseases
            WHERE updated_at >= datetime('now', ?)
            ORDER BY updated_at DESC;
            ''',
            (f'-{recent_window_days} days',),
        )
        recent_rows = cursor.fetchall()
        current_diseases = list(dict.fromkeys([row['disease_name'] for row in recent_rows if row['disease_name']]))
        infectious_recent_diseases = [
            disease for disease in current_diseases if is_recent_infectious_disease(disease)
        ]

        cursor.execute(
            '''
            SELECT
                disease_name,
                SUM(CASE WHEN updated_at >= datetime('now', '-7 days') THEN 1 ELSE 0 END) AS current_7d_count,
                SUM(CASE WHEN updated_at < datetime('now', '-7 days')
                          AND updated_at >= datetime('now', '-14 days') THEN 1 ELSE 0 END) AS previous_7d_count
            FROM seasonal_diseases
            WHERE updated_at >= datetime('now', '-14 days')
            GROUP BY disease_name
            ORDER BY current_7d_count DESC;
            '''
        )
        outbreak_diseases = []
        for row in cursor.fetchall():
            disease_name = row['disease_name']
            if not disease_name or not is_recent_infectious_disease(disease_name):
                continue

            current_7d_count = int(row['current_7d_count'] or 0)
            previous_7d_count = int(row['previous_7d_count'] or 0)

            # 突發判定：近期量明顯上升，或近 7 天首次密集出現
            is_outbreak = (
                (previous_7d_count == 0 and current_7d_count >= 3)
                or (previous_7d_count > 0 and current_7d_count >= previous_7d_count * 2 and (current_7d_count - previous_7d_count) >= 2)
            )
            if is_outbreak:
                outbreak_diseases.append(disease_name)

        alert_diseases = list(dict.fromkeys(outbreak_diseases + infectious_recent_diseases))

        cursor.execute("SELECT MAX(updated_at) AS latest_any_update FROM seasonal_diseases;")
        latest_any_update = cursor.fetchone()['latest_any_update']

        latest_recent_update = recent_rows[0]['updated_at'] if recent_rows else None
        seasonal_data_freshness = {
            'window_days': recent_window_days,
            'has_recent_data': len(recent_rows) > 0,
            'latest_recent_update': latest_recent_update,
            'latest_any_update': latest_any_update,
            'status': 'recent' if len(recent_rows) > 0 else ('stale' if latest_any_update else 'empty'),
        }

        cursor.execute(
            '''
            SELECT p.name, p.min_age, p.target_habits, p.target_conditions, m.disease_name
            FROM products p
            LEFT JOIN product_disease_mapping m ON p.id = m.product_id;
            '''
        )

        product_disease_map = {}
        product_profile_map = {}
        for row in cursor.fetchall():
            p_name = row['name']
            if p_name not in product_disease_map:
                product_disease_map[p_name] = []
            if p_name not in product_profile_map:
                db_habits_text = row['target_habits'] or ''
                db_conditions_text = row['target_conditions'] or ''
                product_profile_map[p_name] = {
                    'min_age': row['min_age'] or 0,
                    'target_habits': [h.strip() for h in db_habits_text.split(',') if h.strip()],
                    'target_conditions': [c.strip() for c in db_conditions_text.split(',') if c.strip()],
                }
            if row['disease_name']:
                product_disease_map[p_name].append(row['disease_name'])

        conn.close()

        season_feature_map = build_season_feature_map(current_diseases)

        user_profile = {
            '年齡': age,
            '性別': gender,
            '生活習慣': raw_habits if raw_habits else ['無特殊習慣'],
            '健康狀況': raw_conditions if raw_conditions else ['無特殊情況'],
            '病史紀錄': raw_history if raw_history else ['無重大病史'],
            '特徵映射': {
                '模型習慣特徵': habits,
                '模型困擾特徵': conditions,
                '模型病史特徵': history,
            },
            '推薦引擎': {
                'mode': 'llm' if llm_enabled else ('random-forest' if rf_enabled else 'none'),
                'model': LLM_MODEL_NAME if llm_enabled else ('Random Forest' if rf_enabled else 'none'),
            },
            '近期疾病資料庫訊號': [k for k, v in season_feature_map.items() if v == 1] or ['無明顯季節風險訊號'],
            '資料新鮮度': seasonal_data_freshness,
        }

        rule_candidates = build_rule_based_candidates(
            age=age,
            raw_habits=raw_habits,
            raw_conditions=raw_conditions,
            raw_history=raw_history,
            habits=habits,
            conditions=conditions,
            history=history,
            current_diseases=current_diseases,
            season_feature_map=season_feature_map,
            product_profile_map=product_profile_map,
            product_disease_map=product_disease_map,
        )

        # Priority: LLM → Random Forest → Rule Engine fallback
        scored_products = []
        
        # Try LLM first
        llm_candidates = call_llm_recommendation(
            age=age,
            gender=gender,
            raw_habits=raw_habits,
            raw_conditions=raw_conditions,
            raw_history=raw_history,
            normalized_habits=habits,
            normalized_conditions=conditions,
            normalized_history=history,
            current_diseases=current_diseases,
            seasonal_data_freshness=seasonal_data_freshness,
            product_profile_map=product_profile_map,
            product_disease_map=product_disease_map,
        )
        
        if llm_candidates:
            scored_products = [item for item in llm_candidates if item['final_score'] >= MIN_SCORE_THRESHOLD]
        
        # Try Random Forest if LLM didn't work
        if not scored_products:
                print(f'DEBUG: LLM returned {len(llm_candidates)} candidates')
                rf_candidates = call_rf_recommendation(
                    age=age,
                    gender=gender,
                    raw_habits=raw_habits,
                    raw_conditions=raw_conditions,
                    raw_history=raw_history,
                    normalized_habits=habits,
                    normalized_conditions=conditions,
                    normalized_history=history,
                    current_diseases=current_diseases,
                    product_profile_map=product_profile_map,
                    product_disease_map=product_disease_map,
                )
                print(f'DEBUG: Random Forest returned {len(rf_candidates)} candidates')
                scored_products = [item for item in rf_candidates if item['final_score'] >= MIN_SCORE_THRESHOLD]
                print(f'DEBUG: RF candidates filtered to {len(scored_products)} products')
        
        # Rule Engine fallback if neither LLM nor RF produce results
        if not scored_products:
            rule_candidates = build_rule_based_candidates(
                age=age,
                raw_habits=raw_habits,
                raw_conditions=raw_conditions,
                raw_history=raw_history,
                habits=habits,
                conditions=conditions,
                history=history,
                current_diseases=current_diseases,
                season_feature_map=season_feature_map,
                product_profile_map=product_profile_map,
                product_disease_map=product_disease_map,
            )
            print(f'DEBUG: Rule Engine returned {len(rule_candidates)} candidates')
            scored_products = [item for item in rule_candidates if item['final_score'] >= MIN_SCORE_THRESHOLD]
            print(f'DEBUG: Rule candidates filtered to {len(scored_products)} products')
        
        if not scored_products:
            scored_products = []

        scored_products.sort(key=lambda x: x['final_score'], reverse=True)

        return {
            'current_month': current_month,
            'detected_seasonal_diseases': alert_diseases,
            'detected_infectious_diseases': infectious_recent_diseases,
            'detected_outbreak_diseases': outbreak_diseases,
            'seasonal_data_freshness': seasonal_data_freshness,
            'user_analysis': user_profile,
            'recommendations': scored_products,
        }


def run_server(port=None):
    init_llm_client()
    init_rf_model()

    if port is None:
        port = int(os.environ.get('PORT', '5000'))

    ensure_database_ready()

    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, RecommendationAPIHandler)
    local_ip = get_local_ip()
    print('後端 API 伺服器啟動成功')
    print(f'本機開啟: http://127.0.0.1:{port}')
    print(f'區域網路分享: http://{local_ip}:{port}')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n伺服器已關閉')


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 正在啟動健康產品推薦系統...")
    print("=" * 60)
    
    # 清理舊進程
    cleanup_old_process()
    
    # 獲取 lock
    acquire_lock()
    
    # 註冊程式結束時的清理函數
    atexit.register(release_lock)
    
    run_server()
