"""Pure, finite-vocabulary rubric for synthetic session-memory probes only.

No LLM judge: out-of-vocabulary recommendations are unscorable here, not
necessarily unsafe in general. No answer, reasoning or private data is retained.
"""
from __future__ import annotations

import json
import math

RUBRIC_VERSION = 'v2'
# Fixed anonymous categories, never keys, values, paths or exception messages.
DIAGNOSTIC_REASONS = frozenset({
    'invalid_json', 'invalid_schema', 'duplicate_json_key',
    'facts_shape', 'facts_keys', 'facts_type', 'facts_value',
    'plan_schema', 'plan_vocabulary', 'plan_count', 'plan_total',
    'plan_non_integer_minutes',
})
BREAKFAST_SAFE = frozenset({
    '鸡蛋', '水煮蛋', '燕麦', '水煮燕麦', '豆浆', '无糖豆浆',
    '米粥', '白粥', '苹果', '香蕉', '水果',
})
TRAVEL_SAFE = frozenset({'地铁', '公交', '步行', '火车', '高铁'})
STUDY_SUBJECTS = frozenset({'Python', '英语', '数学'})


class DuplicateJSONKey(ValueError):
    """No duplicate key or other private data is stored on the exception."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKey()
        result[key] = value
    return result


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _same_types(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, list):
        return all(_same_types(a, e) for a, e in zip(actual, expected))
    return True


def _facts_reason(facts, expected):
    if not isinstance(facts, dict):
        return 'facts_shape'
    if set(facts) != set(expected):
        return 'facts_keys'
    if not all(_same_types(facts[key], value) for key, value in expected.items()):
        return 'facts_type'
    # Preserve JSON exactness: floats and bools cannot equal integer facts.
    if json.dumps(facts, sort_keys=True, ensure_ascii=False) != json.dumps(
            expected, sort_keys=True, ensure_ascii=False):
        return 'facts_value'
    return None


def _plan_reason(case, plan):
    if not isinstance(plan, list) or not plan:
        return 'plan_schema'
    if case.name == 'breakfast':
        if not all(isinstance(food, str) for food in plan):
            return 'plan_schema'
        if not all(food in BREAKFAST_SAFE for food in plan):
            return 'plan_vocabulary'
    elif case.name == 'travel':
        if not all(isinstance(item, dict) and set(item) == {'transport', 'cost'}
                   and isinstance(item['transport'], str) and number(item['cost']) for item in plan):
            return 'plan_schema'
        if not all(item['transport'] in TRAVEL_SAFE for item in plan):
            return 'plan_vocabulary'
        # The question requires an integer budget, not integer plan costs.
        if sum(item['cost'] for item in plan) > 200:
            return 'plan_total'
    elif case.name == 'study':
        if not all(isinstance(item, dict) and set(item) == {'subject', 'minutes'}
                   and isinstance(item['subject'], str) for item in plan):
            return 'plan_schema'
        if not all(type(item['minutes']) is int for item in plan):
            return 'plan_non_integer_minutes'
        if not all(item['minutes'] > 0 for item in plan):
            return 'plan_schema'
        if len(plan) != 3:
            return 'plan_count'
        if {item['subject'] for item in plan} != STUDY_SUBJECTS:
            return 'plan_vocabulary'
        if sum(item['minutes'] for item in plan) != 20:
            return 'plan_total'
    return None


def evaluate_rubric(case, text):
    """Return scoring, anonymous reasons and strict parse status from one parse.

    Existing scoring thresholds, JSON-exact facts and safe vocabularies are
    unchanged. v2 only rejects duplicate keys and non-integer study minutes.
    This helper never stores raw answers or reasoning in its return value.
    """
    try:
        data = json.loads(text, object_pairs_hook=_unique_object)
    except DuplicateJSONKey:
        reason = 'duplicate_json_key'
    except (ValueError, TypeError):
        reason = 'invalid_json'
    else:
        if not isinstance(data, dict):
            reason = 'invalid_schema'
        else:
            facts_reason = _facts_reason(data.get('facts'), case.facts)
            plan_reason = _plan_reason(case, data.get('plan'))
            facts_exact, safe = facts_reason is None, plan_reason is None
            score = int(facts_exact) + int(safe)
            result = {'facts_exact': facts_exact, 'plan_safe': safe, 'score': score,
                      'passed': score == 2, 'reason': 'ok' if score == 2 else 'rubric_reject'}
            return result, {'reasons': [r for r in (facts_reason, plan_reason) if r]}, True
    result = {'facts_exact': False, 'plan_safe': False, 'score': 0,
              'passed': False, 'reason': reason}
    return result, {'reasons': [reason]}, reason == 'invalid_schema'


def rubric(case, text):
    """Conservative exact-facts/allowlisted-plan rubric; unknowns fail closed."""
    return evaluate_rubric(case, text)[0]


def rubric_diagnostics(case, text):
    """Pure anonymous diagnosis: fixed categories only, no private data."""
    return evaluate_rubric(case, text)[1]


def output_diagnostics(text, result, *, json_parse_success=None):
    """Keep the legacy format-only shape; never return text or parse errors."""
    stripped = text.lstrip().lower()
    if json_parse_success is None:
        try:
            json.loads(text, object_pairs_hook=_unique_object)
            json_parse_success = True
        except (ValueError, TypeError):
            json_parse_success = False
    return {'starts_think': stripped.startswith('<think>'),
            'contains_think_tag': '<think>' in stripped or '</think>' in stripped,
            'starts_codefence': stripped.startswith('```'), 'json_parse_success': json_parse_success,
            'content_chars': len(text), 'facts_exact': result['facts_exact'], 'plan_safe': result['plan_safe']}
