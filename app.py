import json
import sqlite3
import datetime
import os
import socket
import pickle
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ai_model = None
product_classes = []

MIN_RECOMMENDATIONS = 3
MIN_SCORE_THRESHOLD = 35
AI_WEIGHT = 0.8
RULE_WEIGHT = 0.2
RULE_SCORE_CAP = 100

try:
    BASE_DIR = Path(__file__).resolve().parent
    with open(BASE_DIR / 'recommendation_model.pkl', 'rb') as f:
        ai_data = pickle.load(f)
        ai_model = ai_data['model']
        product_classes = ai_data['classes']
    print("🤖 AI 推薦模型載入成功！")
except Exception as e:
    print(f"⚠️ 無法載入模型: {e}，請確認是否已執行 train_model.py")
    ai_model = None
BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / 'index.html'
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

    conn.commit()
    conn.close()


def ensure_database_ready():
    init_database()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_local_ip():
    """取得目前電腦在區域網路中的可連線 IP。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))
        return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        sock.close()


def build_season_feature_map(current_diseases):
    """把爬蟲資料庫中的疾病清單轉成模型可用的季節特徵。"""
    joined = ' '.join(current_diseases)
    return {
        "Season_流感": 1 if "流感" in joined else 0,
        "Season_腸病毒": 1 if "腸病毒" in joined else 0,
        "Season_登革熱": 1 if "登革熱" in joined else 0,
        "Season_新冠肺炎": 1 if ("新冠肺炎" in joined or "COVID" in joined) else 0,
        "Season_諾羅病毒": 1 if "諾羅" in joined else 0,
    }


HABIT_ALIAS_MAP = {
    "久坐": ["少運動"],
    "睡眠不足": ["熬夜"],
    "飲食不規律": ["外食"],
}

CONDITION_ALIAS_MAP = {
    "過敏體質": ["免疫力低下"],
    "睡眠品質不佳": ["容易疲勞"],
    "消化不良": ["排便不順"],
    "體能不佳": ["容易疲勞"],
}

HISTORY_ALIAS_MAP = {
    "新冠肺炎": ["流感"],
    "腸病毒": ["腹瀉"],
    "諾羅病毒": ["腹瀉"],
    "登革熱": ["流感"],
    "骨質疏鬆": ["心血管"],
    "失眠": ["流感"],
}

# 擴充選項（前端新增項目）對產品推薦的加權規則
# 關鍵字會在「產品名稱 + 產品設定 + 疾病對應」中比對，命中即加分並產生理由。
EXTRA_HABIT_KEYWORDS = {
    "久坐": ["少運動", "關節", "心血管", "三高", "循環"],
    "睡眠不足": ["睡眠", "失眠", "疲勞", "B群", "鎂"],
    "飲食不規律": ["外食", "消化", "腸胃", "益生菌", "消化酵素"],
    "健身": ["蛋白", "肌肉", "體能"],
    "運動量大": ["電解質", "蛋白", "體能", "鎂"],
    "喝水少": ["泌尿", "膳食纖維", "益生菌", "消化"],
    "勞力工作": ["關節", "葡萄糖胺", "鎂", "體能"],
}

EXTRA_CONDITION_KEYWORDS = {
    "過敏體質": ["過敏", "鼻炎", "氣喘", "益生菌"],
    "三高風險": ["心血管", "高血脂", "紅麴", "魚油", "輔酶Q10"],
    "睡眠品質不佳": ["失眠", "睡眠", "鎂", "B群", "疲勞"],
    "消化不良": ["消化", "腸胃", "消化酵素", "益生菌", "膳食纖維"],
    "體能不佳": ["體能", "蛋白", "B群", "輔酶Q10", "電解質"],
    "眼睛疲勞": ["眼睛", "葉黃素", "乾眼"],
    "皮膚乾燥": ["皮膚", "膠原蛋白", "維他命E", "抗氧化"],
}

EXTRA_HISTORY_KEYWORDS = {
    "新冠肺炎": ["新冠", "呼吸道", "流感", "免疫"],
    "失眠": ["失眠", "睡眠", "疲勞", "鎂", "B群"],
    "腸病毒": ["腸病毒", "腸胃", "腹瀉", "益生菌"],
    "諾羅病毒": ["諾羅", "腸胃", "腹瀉", "益生菌"],
    "登革熱": ["登革熱", "流感", "免疫"],
    "骨質疏鬆": ["骨質", "鈣D3", "關節", "葡萄糖胺"],
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
    habits_text = ' '.join(profile.get("target_habits", []))
    conditions_text = ' '.join(profile.get("target_conditions", []))
    disease_text = ' '.join(preventable)
    return f"{prod_name} {habits_text} {conditions_text} {disease_text}"


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
        reasons.append(f"{reason_prefix}：{item}（+{bonus}）")
        summaries.append(f"{summary_prefix}「{item}」與產品特性關聯，提升推薦指數")

    return min(score, 30), reasons, summaries


def build_model_features(age, gender, habits, conditions, history, season_feature_map):
    """組合模型輸入：使用者個資 + 當月疾病資料庫特徵。"""
    gender_val = 1 if gender == '男' else 0
    return [[
        age, gender_val,
        1 if '外食' in habits else 0,
        1 if '熬夜' in habits else 0,
        1 if '壓力大' in habits else 0,
        1 if '少運動' in habits else 0,
        1 if '容易疲勞' in conditions else 0,
        1 if '免疫力低下' in conditions else 0,
        1 if '排便不順' in conditions else 0,
        1 if '關節不適' in conditions else 0,
        1 if '流感' in history else 0,
        1 if '腹瀉' in history else 0,
        1 if '過敏' in history else 0,
        1 if '心血管' in history else 0,
        season_feature_map["Season_流感"],
        season_feature_map["Season_腸病毒"],
        season_feature_map["Season_登革熱"],
        season_feature_map["Season_新冠肺炎"],
        season_feature_map["Season_諾羅病毒"],
    ]]

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
    
    def _set_cors_headers(self):
        """設定跨域存取（CORS）。"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
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
        """處理平台健康檢查的 HEAD 請求。"""
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
        """處理瀏覽器的預檢請求。"""
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        """處理前端傳來的資料並計算推薦結果。"""
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
                
                recommend_results = self.calculate_recommendations(user_age, user_gender, user_habits, user_conditions, user_history)
                
                self._send_json(200, recommend_results)
            except Exception as exc:
                self._send_json(500, {
                    "error": str(exc),
                    "message": "後端推薦計算失敗"
                })
        else:
            self._send_json(404, {"error": "not found"})

    def calculate_recommendations(self, age, gender, habits, conditions, history):
        global ai_model, product_classes
        """核心推薦演算法：AI 讀取使用者資料與爬蟲疾病資料庫後進行推薦。"""
        current_month = datetime.datetime.now().month
        recent_window_days = 30
        raw_habits = list(habits)
        raw_conditions = list(conditions)
        raw_history = list(history)
        habits, conditions, history = normalize_user_inputs(habits, conditions, history)
        
        # 1. 從資料庫撈出「最近 N 天有效」疾病資料
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT disease_name, updated_at
            FROM seasonal_diseases
            WHERE updated_at >= datetime('now', ?)
            ORDER BY updated_at DESC;
            ''',
            (f'-{recent_window_days} days',)
        )
        recent_rows = cursor.fetchall()
        current_diseases = list(dict.fromkeys([row['disease_name'] for row in recent_rows if row['disease_name']]))

        cursor.execute("SELECT MAX(updated_at) AS latest_any_update FROM seasonal_diseases;")
        latest_any_update = cursor.fetchone()['latest_any_update']

        latest_recent_update = recent_rows[0]['updated_at'] if recent_rows else None
        seasonal_data_freshness = {
            "window_days": recent_window_days,
            "has_recent_data": len(recent_rows) > 0,
            "latest_recent_update": latest_recent_update,
            "latest_any_update": latest_any_update,
            "status": "recent" if len(recent_rows) > 0 else ("stale" if latest_any_update else "empty")
        }
        
        # 撈出資料庫中的產品條件與疾病對應。
        # 注意：若資料庫沒有對應資料，系統仍可用 AI 機率分數完成推薦。
        cursor.execute('''
            SELECT p.name, p.min_age, p.target_habits, p.target_conditions, m.disease_name 
            FROM products p 
            LEFT JOIN product_disease_mapping m ON p.id = m.product_id;
        ''')
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
                    "min_age": row['min_age'] or 0,
                    "target_habits": [h.strip() for h in db_habits_text.split(',') if h.strip()],
                    "target_conditions": [c.strip() for c in db_conditions_text.split(',') if c.strip()]
                }
            if row['disease_name']:
                product_disease_map[p_name].append(row['disease_name'])
        conn.close()

        # 2. 準備 AI 模型特徵（使用者輸入 + 當月爬蟲疾病特徵）
        season_feature_map = build_season_feature_map(current_diseases)
        features = build_model_features(age, gender, habits, conditions, history, season_feature_map)
        
        # 記錄用戶輸入的分析
        user_profile = {
            "年齡": age,
            "性別": gender,
            "生活習慣": raw_habits if raw_habits else ["無特殊習慣"],
            "健康狀況": raw_conditions if raw_conditions else ["無特殊情況"],
            "病史紀錄": raw_history if raw_history else ["無重大病史"],
            "特徵映射": {
                "模型習慣特徵": habits,
                "模型困擾特徵": conditions,
                "模型病史特徵": history,
            },
            "擴充選項計分": "已啟用",
            "近期疾病資料庫訊號": [k for k, v in season_feature_map.items() if v == 1] or ["無明顯季節風險訊號"],
            "資料新鮮度": seasonal_data_freshness
        }

        scored_products = []

        # 3. 如果 AI 模型已載入，進行預測
        if ai_model is not None:
            model_feature_count = getattr(ai_model, 'n_features_in_', None)
            if model_feature_count and model_feature_count != len(features[0]):
                return {
                    "current_month": current_month,
                    "detected_seasonal_diseases": current_diseases,
                    "seasonal_data_freshness": seasonal_data_freshness,
                    "user_analysis": user_profile,
                    "recommendations": [],
                    "error": f"模型特徵數不相容: 目前模型需要 {model_feature_count} 維，但後端輸入為 {len(features[0])} 維。請重新執行 generate_data.py 與 train_model.py。"
                }

            # predict_proba 回傳每個產品的機率 (0.0~1.0)
            probabilities = ai_model.predict_proba(features)[0]
            candidate_products = []

            history_to_keywords = {
                "流感": ["流感", "感冒", "呼吸道"],
                "腹瀉": ["腹瀉", "腸胃炎", "食物中毒"],
                "過敏": ["過敏", "鼻炎", "氣喘"],
                "心血管": ["心血管", "高血脂", "三高"]
            }
            
            for idx, prod_name in enumerate(product_classes):
                ai_score = int(probabilities[idx] * 100) # 將機率轉為 0-100 分
                rule_score = 0

                profile = product_profile_map.get(prod_name, {"min_age": 0, "target_habits": [], "target_conditions": []})
                min_age = profile["min_age"]
                target_habits = profile["target_habits"]
                target_conditions = profile["target_conditions"]
                preventable = product_disease_map.get(prod_name, [])
                product_search_text = build_product_search_text(prod_name, profile, preventable)

                # 年齡未達建議值時略過該產品。
                if age < min_age:
                    continue

                matching_reasons = [f"🤖 AI 分析相容度：{ai_score}%"]
                summary_parts = []

                active_season_signals = [name.replace('Season_', '') for name, val in season_feature_map.items() if val == 1]
                if active_season_signals:
                    matching_reasons.append(f"🌡️ AI 已納入當月疾病訊號：{'、'.join(active_season_signals)}")
                    summary_parts.append("本次 AI 預測已同時考慮使用者填答與爬蟲資料庫中的當月疾病風險")

                matched_habits = [h for h in habits if h in target_habits]
                if matched_habits:
                    base_habit_bonus = 8 + len(matched_habits) * 2
                    rule_score += base_habit_bonus
                    matched_text = '、'.join(matched_habits)
                    matching_reasons.append(f"🧩 資料庫習慣匹配：{matched_text}")
                    summary_parts.append(f"你填寫的生活習慣「{matched_text}」符合這項產品的建議情境")

                matched_conditions = [c for c in conditions if c in target_conditions]
                if matched_conditions:
                    base_condition_bonus = 10 + len(matched_conditions) * 2
                    rule_score += base_condition_bonus
                    matched_text = '、'.join(matched_conditions)
                    matching_reasons.append(f"💡 資料庫困擾匹配：{matched_text}")
                    summary_parts.append(f"你目前的健康困擾「{matched_text}」與此產品的目標需求一致")

                matched_history = []
                for h in history:
                    keywords = history_to_keywords.get(h, [])
                    if any(any(k in disease for k in keywords) for disease in preventable):
                        matched_history.append(h)

                if matched_history:
                    rule_score += 20
                    matched_text = '、'.join(matched_history)
                    matching_reasons.append(f"🛡️ 資料庫病史關聯：{matched_text}")
                    summary_parts.append(f"你填寫的病史「{matched_text}」與這項產品的保養方向有直接關聯")

                # 混合邏輯：如果該產品在資料庫對應到當季流行病，進行加權
                for disease in preventable:
                    if disease in current_diseases:
                        rule_score += 30 # 若命中當季流行病，大幅加分
                        matching_reasons.append(f"🌍 資料庫季節防護：【{disease}】")
                        summary_parts.append(f"目前季節風險包含「{disease}」，此產品可提供對應防護")

                # 針對前端新增項目做額外關聯加權，並回傳可讀解釋
                habit_bonus, habit_reasons, habit_summaries = score_extra_options(
                    raw_habits,
                    EXTRA_HABIT_KEYWORDS,
                    product_search_text,
                    "🧭 延伸習慣關聯",
                    "你填寫的生活習慣",
                )
                if habit_bonus > 0:
                    rule_score += habit_bonus
                    matching_reasons.extend(habit_reasons)
                    summary_parts.extend(habit_summaries)

                condition_bonus, condition_reasons, condition_summaries = score_extra_options(
                    raw_conditions,
                    EXTRA_CONDITION_KEYWORDS,
                    product_search_text,
                    "🩺 延伸困擾關聯",
                    "你填寫的健康困擾",
                )
                if condition_bonus > 0:
                    rule_score += condition_bonus
                    matching_reasons.extend(condition_reasons)
                    summary_parts.extend(condition_summaries)

                history_bonus, history_reasons, history_summaries = score_extra_options(
                    raw_history,
                    EXTRA_HISTORY_KEYWORDS,
                    product_search_text,
                    "📚 延伸病史關聯",
                    "你填寫的歷史紀錄",
                )
                if history_bonus > 0:
                    rule_score += history_bonus
                    matching_reasons.extend(history_reasons)
                    summary_parts.extend(history_summaries)

                normalized_rule_score = min(RULE_SCORE_CAP, rule_score)
                final_score = int(round(ai_score * AI_WEIGHT + normalized_rule_score * RULE_WEIGHT))
                matching_reasons.append(f"⚖️ 混合評分：AI {int(AI_WEIGHT * 100)}% + 規則 {int(RULE_WEIGHT * 100)}%")
                summary_parts.append(
                    f"最終推薦指數 = AI分數({ai_score})×{AI_WEIGHT:.1f} + 規則分數({normalized_rule_score})×{RULE_WEIGHT:.1f}"
                )

                if min_age > 0:
                    summary_parts.append(f"你的年齡 {age} 歲已達建議使用年齡 {min_age} 歲")

                if summary_parts:
                    analysis_summary = "；".join(summary_parts) + "。"
                else:
                    analysis_summary = "主要根據你的整體填答特徵與 AI 模型分數進行推薦。"

                candidate_products.append({
                    "product_name": prod_name,
                    "final_score": final_score,
                    "ai_confidence": probabilities[idx],
                    "reasons": matching_reasons,
                    "analysis_summary": analysis_summary
                })

            candidate_products.sort(key=lambda x: x["final_score"], reverse=True)

            # 只保留超過門檻分數的產品，不補充低分產品
            scored_products = [item for item in candidate_products if item["final_score"] > MIN_SCORE_THRESHOLD]

        # 4. 排序並回傳
        scored_products.sort(key=lambda x: x["final_score"], reverse=True)

        print(f"DEBUG: 預測出的產品清單為: {scored_products}")
        return {
            "current_month": current_month,
            "detected_seasonal_diseases": current_diseases,
            "seasonal_data_freshness": seasonal_data_freshness,
            "user_analysis": user_profile,
            "recommendations": scored_products
        }

def run_server(port=None):
    if port is None:
        port = int(os.environ.get('PORT', '5000'))

    ensure_database_ready()

    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, RecommendationAPIHandler)
    local_ip = get_local_ip()
    print(f"🎉 後端 API 伺服器已成功啟動！")
    print(f"本機開啟: http://127.0.0.1:{port}")
    print(f"區域網路分享: http://{local_ip}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 伺服器已安全關閉。")

if __name__ == '__main__':
    run_server()