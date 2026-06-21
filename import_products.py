import csv
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "health_system.db"
DEFAULT_CSV_PATH = BASE_DIR / "product_import_template.csv"


def ensure_tables(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            min_age INTEGER DEFAULT 0,
            target_habits TEXT,
            target_conditions TEXT
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS product_disease_mapping (
            product_id INTEGER,
            disease_name TEXT,
            PRIMARY KEY (product_id, disease_name),
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        """
    )


def parse_csv_rows(csv_path):
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 CSV 檔案: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"name", "min_age", "target_habits", "target_conditions", "diseases"}
        if not required.issubset(set(reader.fieldnames or [])):
            missing = sorted(required - set(reader.fieldnames or []))
            raise ValueError(f"CSV 缺少必要欄位: {', '.join(missing)}")

        rows = []
        for idx, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            if not name:
                raise ValueError(f"第 {idx} 行 name 為空")

            min_age_raw = (row.get("min_age") or "0").strip()
            try:
                min_age = int(min_age_raw)
            except ValueError as exc:
                raise ValueError(f"第 {idx} 行 min_age 不是整數: {min_age_raw}") from exc

            target_habits = (row.get("target_habits") or "").strip()
            target_conditions = (row.get("target_conditions") or "").strip()

            diseases_raw = (row.get("diseases") or "").strip()
            diseases = [d.strip() for d in diseases_raw.split("|") if d.strip()]

            rows.append(
                {
                    "name": name,
                    "min_age": min_age,
                    "target_habits": target_habits,
                    "target_conditions": target_conditions,
                    "diseases": diseases,
                }
            )

    if not rows:
        raise ValueError("CSV 沒有可匯入的資料列")

    return rows


def import_products(csv_path=DEFAULT_CSV_PATH):
    rows = parse_csv_rows(csv_path)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)
    cursor = conn.cursor()

    imported_products = 0
    imported_mappings = 0

    try:
        for row in rows:
            cursor.execute(
                """
                INSERT INTO products (name, min_age, target_habits, target_conditions)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    min_age = excluded.min_age,
                    target_habits = excluded.target_habits,
                    target_conditions = excluded.target_conditions;
                """,
                (
                    row["name"],
                    row["min_age"],
                    row["target_habits"],
                    row["target_conditions"],
                ),
            )

            cursor.execute("SELECT id FROM products WHERE name = ?;", (row["name"],))
            product_id = cursor.fetchone()["id"]
            imported_products += 1

            # 讓 mapping 與 CSV 保持一致：先刪該產品舊映射，再寫入新映射
            cursor.execute("DELETE FROM product_disease_mapping WHERE product_id = ?;", (product_id,))

            for disease_name in row["diseases"]:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO product_disease_mapping (product_id, disease_name)
                    VALUES (?, ?);
                    """,
                    (product_id, disease_name),
                )
                imported_mappings += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("匯入完成")
    print(f"products 更新筆數: {imported_products}")
    print(f"product_disease_mapping 寫入筆數: {imported_mappings}")
    print(f"使用 CSV: {csv_path}")
    print(f"目標資料庫: {DB_PATH}")


if __name__ == "__main__":
    import_products()
