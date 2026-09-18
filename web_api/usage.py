"""Public usage projections; never expose the shared ledger or another owner's turns."""
import time
from decimal import Decimal


def summarize(attempts, turn_ids, mode):
    rows = [a for a in attempts if a['turn_id'] in turn_ids] if mode == 'live' else []
    known = [a for a in rows if 'actual_cny' in a]
    pending = [a for a in rows if 'actual_cny' not in a]
    def total(key):
        return sum((Decimal(str(a.get(key, 0))) for a in rows), Decimal(0))
    return {
        'mode': mode, 'estimated_cny': float(total('actual_cny')),
        'pending_reserved_cny': float(sum((Decimal(str(a['reserved_cny'])) for a in pending), Decimal(0))),
        'request_count': len(rows), 'settled_requests': len(known), 'pending_requests': len(pending),
        'input_tokens': sum(a['raw_usage']['prompt_tokens'] for a in known),
        'output_tokens': sum(a['raw_usage']['completion_tokens'] for a in known),
        'cache_hit_tokens': sum(a['raw_usage']['prompt_cache_hit_tokens'] for a in known),
        'updated_at': time.time(), 'basis': 'recorded_usage_local_tariff',
    }
