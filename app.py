import json
import sqlite3
import datetime
import os
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from init_db import init_database


BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / 'index.html'


def ensure_database_ready():
    init_database()

def get_db_connection():
    conn = sqlite3.connect('health_system.db')
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
        """設定跨域存取（CORS），讓以後的前端網頁能順利呼叫這個 API"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*') # 允許任何前端網頁存取
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
        """處理瀏覽器的預檢請求（Preflight Request）"""
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        """處理前端傳送過來的資料，並計算推薦結果"""
        if self.path == '/api/recommend':
            try:
                # 1. 讀取前端傳來的 JSON 資料
                content_length = int(self.headers.get('Content-Length', '0'))
                post_data = self.rfile.read(content_length)
                user_input = json.loads(post_data.decode('utf-8'))
                
                user_age = int(user_input.get('age', 0))
                user_habits = user_input.get('habits', [])
                user_conditions = user_input.get('conditions', [])
                user_history = user_input.get('history', [])
                
                # 2. 計算推薦
                recommend_results = self.calculate_recommendations(user_age, user_habits, user_conditions, user_history)
                
                # 3. 回傳 JSON 結果給前端
                self._send_json(200, recommend_results)
            except Exception as exc:
                self._send_json(500, {
                    "error": str(exc),
                    "message": "後端推薦計算失敗"
                })
        else:
            self._send_json(404, {"error": "not found"})

    def calculate_recommendations(self, age, habits, conditions, history):
        """核心推薦演算法邏輯"""
        current_month = datetime.datetime.now().month
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # A. 撈出當月高風險的季節性疾病
        cursor.execute("SELECT disease_name FROM seasonal_diseases WHERE month = ?;", (current_month,))
        current_diseases = [row['disease_name'] for row in cursor.fetchall()]
        
        # B. 撈出所有的保健食品，以及它們能預防的疾病
        cursor.execute('''
            SELECT p.id, p.name, p.min_age, p.target_habits, p.target_conditions, m.disease_name
            FROM products p
            LEFT JOIN product_disease_mapping m ON p.id = m.product_id;
        ''')
        rows = cursor.fetchall()
        
        # 整理產品資料結構
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
        
        conn.close()
        
        # C. 開始幫每個產品計分
        scored_products = []
        for pid, prod in products_dict.items():
            # 門檻檢查：如果使用者年齡小於產品最低限制，直接淘汰不推薦
            if age < prod["min_age"]:
                continue
                
            score = 0
            matching_reasons = []
            
            # 評分項目 1：生活習慣比對 (符合一項 +2 分)
            for habit in habits:
                if habit in prod["target_habits"]:
                    score += 2
                    matching_reasons.append(f"符合你的生活習慣【{habit}】")
                    
            # 評分項目 2：健康狀況比對 (符合一項 +3 分，權重較高)
            for condition in conditions:
                if condition in prod["target_conditions"]:
                    score += 3
                    matching_reasons.append(f"針對你的健康狀況【{condition}】")

            # 評分項目 2.5：歷史健康紀錄比對 (符合一項 +2 分)
            for history_item in history:
                if history_item in prod["target_conditions"] or history_item in prod["prevent_diseases"]:
                    score += 2
                    matching_reasons.append(f"對應你的歷史健康紀錄【{history_item}】")
            
            # 評分項目 3：季節性流行疾病預防 (如果能預防當季流行病，大加分 +5 分！)
            for disease in prod["prevent_diseases"]:
                if disease in current_diseases:
                    score += 5
                    matching_reasons.append(f"預防當季熱門流行疾病【{disease}】")
            
            # 只要分數大於 0，就納入推薦清單
            if score > 0:
                scored_products.append({
                    "product_name": prod["name"],
                    "final_score": score,
                    "reasons": matching_reasons
                })
        
        # D. 根據總分從高到低進行排序
        scored_products.sort(key=lambda x: x["final_score"], reverse=True)
        
        return {
            "current_month": current_month,
            "detected_seasonal_diseases": current_diseases,
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