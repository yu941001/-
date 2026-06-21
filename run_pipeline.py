import argparse
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def run_step(title, script_name):
    script_path = BASE_DIR / script_name
    if not script_path.exists():
        print(f"[ERROR] Missing script: {script_name}")
        raise SystemExit(1)

    print("\n" + "=" * 70)
    print(f"[STEP] {title}")
    print(f"[RUN ] {sys.executable} {script_name}")
    print("=" * 70)

    result = subprocess.run([sys.executable, str(script_path)], cwd=str(BASE_DIR))
    if result.returncode != 0:
        print(f"\n[FAIL] Step failed: {title} (exit code {result.returncode})")
        raise SystemExit(result.returncode)

    print(f"[OK  ] {title}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run the full recommendation pipeline: "
            "import products -> crawl diseases -> generate data -> train model -> start server"
        )
    )
    parser.add_argument(
        "--no-server",
        action="store_true",
        help="Run steps 1-4 only and skip starting app.py",
    )
    args = parser.parse_args()

    print("[INFO] Pipeline started")
    print(f"[INFO] Project directory: {BASE_DIR}")

    run_step("1) Import products and mappings", "import_products.py")
    run_step("2) Crawl seasonal diseases", "safe_crawler.py")
    run_step("3) Generate training dataset", "generate_data.py")
    run_step("4) Train recommendation model", "train_model.py")

    if args.no_server:
        print("\n[DONE] Steps 1-4 completed. Server start was skipped (--no-server).")
        return

    print("\n[DONE] Steps 1-4 completed. Starting API server...")
    run_step("5) Start recommendation API server", "app.py")


if __name__ == "__main__":
    main()
