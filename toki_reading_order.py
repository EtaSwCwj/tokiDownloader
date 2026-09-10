"""Pure O(n log n) reading-order policy; source numbers/IDs remain unchanged.

The downloader uses the JS equivalent. Shared rules and cross-runtime fixtures
prevent folder migration and ZIP ordering from diverging.
"""
import json
import math
import re
import unicodedata
from pathlib import Path

RULES = json.loads(Path(__file__).with_name('episode_reading_order_rules.json').read_text(encoding='utf-8'))
EXPLICIT = re.compile(RULES['numberPattern'] + r'\s*(' + RULES['units'] + ')')
ENDING = re.compile(RULES['numberPattern'] + r'\s*(?:화|권|회|장)?\s*(?:\(완결\)|완결|完)?$')
MARKERS = re.compile(r'(?:^|[\s(])(' + '|'.join(re.escape(n) for g in RULES['extraGroups'] for n in g) + r')(?=$|[\s)0-9])')


def _normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or ''))).strip().lower()


def assign_reading_order(records, work_title=''):
    work = _normalize(work_title)
    compact_work = re.sub(r'\s', '', work)
    prefix = re.compile('^' + r'\s*'.join(re.escape(c) for c in compact_work)
                        + r'(?=$|[\s(0-9:：-])\s*') if work else None

    def classify(record):
        text = _normalize(record.get('sourceTitle') or record.get('displayTitle'))
        if re.sub(r'\s', '', text) == compact_work:
            text = ''
        else:
            text = re.split(r'…|\.{3}', text)[-1].strip()
            if prefix:
                text = prefix.sub('', text).strip()
        def unknown(warning):
            return dict(group='source', warning=warning, unit='', key=None)
        if not text or record.get('numberInferred'):
            return unknown('unnumbered')
        if re.search(r'[0-9]+(?:\.[0-9]+)?\s*[~～–—]\s*[0-9]+', text) or re.search(r'[0-9]+\s*(?:부|시즌)', text):
            return unknown('ambiguous_context')
        marker = MARKERS.search(text)
        matches = list(EXPLICIT.finditer(text))
        before = [m for m in matches if m.start() < marker.start()] if marker else []
        group, extra, attached = 'main', -1, 0
        if marker and len(before) == 1:
            match, attached, group = before[0], 1, 'attached'
        elif marker and not before:
            extra = next(i for i, names in enumerate(RULES['extraGroups']) if marker[1] in names)
            match = ENDING.search(text[marker.end():].strip())
            if not match or match.start() != 0:
                return unknown('unnumbered_extra')
            group = 'extra'
        elif marker or len(matches) > 1:
            return unknown('ambiguous_number')
        else:
            match = matches[0] if matches else ENDING.search(text)
        if not match:
            return unknown('unnumbered')
        value, part = float(f'{match[1]}.{match[2] or "0"}'), int(match[3] or 0)
        if not math.isfinite(value) or value > 1e9 or part > 1e9:
            return unknown('number_limit')
        return dict(group=group, extra=extra, warning='', unit=match[4] if len(match.groups()) > 3 else '',
                    key=(value, part, attached))

    rows = [dict(record=r, index=i, **classify(r)) for i, r in enumerate(records)]
    source = sorted(rows, key=lambda r: (int(r['record']['number']), r['index']))
    units = {r['unit'] for r in rows if r['group'] != 'extra' and r['unit']}
    for row in rows:
        if not row['unit'] and row['key'] is not None and row['group'] != 'extra':
            if len(units) > 1:
                row.update(key=None, warning='mixed_units', group='source')
            else:
                row['unit'] = next(iter(units), '')
    def key(row):
        return (*row['key'], int(row['record']['number']), row['index'])
    ordered, run = [], []
    def flush():
        ordered.extend(sorted(run, key=key))
        run.clear()
    for row in (r for r in source if r['group'] != 'extra'):
        if row['key'] is None:
            flush()
            ordered.append(row)
        else:
            if run and run[0]['unit'] != row['unit']:
                flush()
            run.append(row)
    flush()
    ordered.extend(sorted((r for r in source if r['group'] == 'extra'), key=lambda r: (r['extra'], *key(r))))
    slots = [int(r['record']['number']) for r in source]
    unique_slots = all(n > 0 for n in slots) and len(set(slots)) == len(slots)
    result = [None] * len(rows)
    for index, row in enumerate(ordered):
        result[row['index']] = dict(row['record'], readingOrder=slots[index] if unique_slots else index+1,
                                   readingOrderVersion=RULES['version'], readingGroup=row['group'], readingOrderWarning=row['warning'])
    return result


def reading_order_warnings(records):
    return [{'number':r['number'], 'sourceId':r.get('sourceId',''), 'sourceTitle':r.get('sourceTitle',''),
             'reason':r['readingOrderWarning'], 'message':RULES['warningLabels'].get(r['readingOrderWarning'],r['readingOrderWarning'])}
            for r in records if r.get('readingOrderWarning')]
