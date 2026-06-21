import json
import sqlite3
import datetime
import os
import socket
import pickle
import numpy as np
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ai_model = None
product_classes = []

MIN_RECOMMENDATIONS = 3
MIN_SCORE_THRESHOLD = 35

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

    sample_products = [
        ("綜合維他命", 12, "外食,熬夜", "容易疲勞"),
        ("高濃度維他命C", 0, "壓力大", "免疫力低下"),
        ("益生菌", 0, "外食", "排便不順,過敏體質"),
        ("深海魚油", 18, "外食,少運動", "三高風險"),
        ("葡萄糖胺", 50, "久站,勞力工作", "關節不適"),
        ("B群", 12, "熬夜,壓力大", "精神不濟"),
        ("葉黃素", 18, "長時間用眼,3C工作", "眼睛疲勞"),
        ("鈣D3", 40, "少曬太陽,少運動", "骨骼保養"),
        ("薑黃素", 30, "外食,久坐", "發炎體質")
    ]

    for prod in sample_products:
        cursor.execute('''
        INSERT OR IGNORE INTO products (name, min_age, target_habits, target_conditions)
        VALUES (?, ?, ?, ?);
        ''', prod)

    sample_mappings = [
        ("綜合維他命", "感冒"),
        ("高濃度維他命C", "流感"),
        ("高濃度維他命C", "呼吸道融合病毒"),
        ("益生菌", "過敏性鼻炎"),
        ("益生菌", "食物中毒/急性腸胃炎"),
        ("深海魚油", "氣喘/心血管疾病"),
        ("葡萄糖胺", "關節炎"),
        ("B群", "感冒"),
        ("葉黃素", "乾眼症"),
        ("鈣D3", "骨質疏鬆"),
        ("薑黃素", "發炎反應")
    ]

    for prod_name, disease in sample_mappings:
        cursor.execute("SELECT id FROM products WHERE name = ?;", (prod_name,))
        row = cursor.fetchone()
        if row:
            cursor.execute('''
            INSERT OR IGNORE INTO product_disease_mapping (product_id, disease_name)
            VALUES (?, ?);
            ''', (row[0], disease))

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
        """核心推薦演算法：AI 預測機率 + 季節性疾病加權 (Hybrid Model)"""
        current_month = datetime.datetime.now().month
        
        # 1. 從資料庫撈出當季高風險疾病
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT disease_name FROM seasonal_diseases WHERE month = ?;", (current_month,))
        current_diseases = [row['disease_name'] for row in cursor.fetchall()]
        
        # 撈出所有產品與其對應的預防疾病
        cursor.execute('''
            SELECT p.name, m.disease_name 
            FROM products p 
            LEFT JOIN product_disease_mapping m ON p.id = m.product_id;
        ''')
        product_disease_map = {}
        for row in cursor.fetchall():
            p_name = row['name']
            if p_name not in product_disease_map:
                product_disease_map[p_name] = []
            if row['disease_name']:
                product_disease_map[p_name].append(row['disease_name'])
        conn.close()

        # 2. 準備 AI 模型需要的特徵 (順序必須與訓練時完全一致)
        # 順序: Age, Gender(1=男,0=女), 外食, 熬夜, 壓力大, 少運動, 疲勞, 免疫力, 排便, 關節, 流感感冒, 腸病毒腹瀉, 過敏紀錄, 三高心血管
        gender_val = 1 if gender == '男' else 0
        features = [[
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
        ]]
        
        # 記錄用戶輸入的分析
        user_profile = {
            "年齡": age,
            "性別": gender,
            "生活習慣": habits if habits else ["無特殊習慣"],
            "健康狀況": conditions if conditions else ["無特殊情況"],
            "病史紀錄": history if history else ["無重大病史"]
        }

        scored_products = []

        # 3. 如果 AI 模型已載入，進行預測
        if ai_model is not None:
            # predict_proba 回傳每個產品的機率 (0.0~1.0)
            probabilities = ai_model.predict_proba(features)[0]
            candidate_products = []
            
            for idx, prod_name in enumerate(product_classes):
                ai_score = int(probabilities[idx] * 100) # 將機率轉為 0-100 分

                matching_reasons = [f"🤖 AI 分析相容度：{ai_score}%"]

                if any(k in history for k in ['流感', '腹瀉', '過敏', '心血管']):
                    ai_score += 20 # 分數加權
                    matching_reasons.append("🛡️ 您的病史記錄與此產品高度相關")

                # 混合邏輯：如果該產品能預防當季流行病，進行加權
                preventable = product_disease_map.get(prod_name, [])
                for disease in preventable:
                    if disease in current_diseases:
                        ai_score += 30 # 若命中當季流行病，大幅加分
                        matching_reasons.append(f"🌍 當季流行病防護：【{disease}】")

                candidate_products.append({
                    "product_name": prod_name,
                    "final_score": ai_score,
                    "ai_confidence": probabilities[idx],
                    "reasons": matching_reasons
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