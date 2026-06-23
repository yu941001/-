"""
共用工具函數
在所有模組間共享，避免重複定義
"""

from typing import Any, Tuple
import json
from config import (
    HABIT_ALIAS_MAP,
    CONDITION_ALIAS_MAP,
    HISTORY_ALIAS_MAP,
    EXTRA_HABIT_KEYWORDS,
    EXTRA_CONDITION_KEYWORDS,
    EXTRA_HISTORY_KEYWORDS,
    HISTORY_TO_KEYWORDS,
    RULE_SCORE_CAP,
)


def expand_with_aliases(items: list[str], alias_map: dict[str, list[str]]) -> list[str]:
    """將用戶輸入通過別名映射展開。"""
    expanded = set(items)
    for item in list(expanded):
        for alias in alias_map.get(item, []):
            expanded.add(alias)
    return sorted(expanded)


def normalize_user_inputs(
    habits: list[str],
    conditions: list[str],
    history: list[str],
) -> Tuple[list[str], list[str], list[str]]:
    """正規化用戶輸入（展開別名）。"""
    norm_habits = expand_with_aliases(habits, HABIT_ALIAS_MAP)
    norm_conditions = expand_with_aliases(conditions, CONDITION_ALIAS_MAP)
    norm_history = expand_with_aliases(history, HISTORY_ALIAS_MAP)
    return norm_habits, norm_conditions, norm_history


def build_product_search_text(
    prod_name: str,
    target_habits: list[str],
    target_conditions: list[str],
    preventable_diseases: list[str],
) -> str:
    """構建產品搜索文本用於關鍵字匹配。"""
    habits_text = ' '.join(target_habits)
    conditions_text = ' '.join(target_conditions)
    disease_text = ' '.join(preventable_diseases)
    return f'{prod_name} {habits_text} {conditions_text} {disease_text}'


def score_extra_options(
    raw_items: list[str],
    keyword_map: dict[str, list[str]],
    search_text: str,
    reason_prefix: str,
    summary_prefix: str,
) -> Tuple[int, list[str], list[str]]:
    """
    計算延伸關鍵字匹配分數與原因。
    
    Returns:
        (分數, 理由列表, 摘要列表)
    """
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
    product_search_text = build_product_search_text(
        product_name, target_habits, target_conditions, preventable_diseases
    )
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


def parse_list_field(value: Any) -> list[str]:
    """將 JSON/CSV/純字串轉為字串陣列。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith('['):
            try:
                arr = json.loads(text)
                if isinstance(arr, list):
                    return [str(item).strip() for item in arr if str(item).strip()]
            except json.JSONDecodeError:
                pass
        return [item.strip() for item in text.split(',') if item.strip()]
    return []


def parse_product_scores_field(value: Any) -> dict[str, float]:
    """將產品分數欄位轉為 {product_name: score}。"""
    if value is None:
        return {}

    if isinstance(value, dict):
        return {str(k): float(v) for k, v in value.items()}

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                result = {}
                for key, score in parsed.items():
                    try:
                        result[str(key)] = float(score)
                    except (TypeError, ValueError):
                        continue
                return result
        except json.JSONDecodeError:
            return {}

    return {}
