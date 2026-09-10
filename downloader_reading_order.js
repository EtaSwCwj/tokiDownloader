// Node/Python share a declarative policy and cross-runtime fixtures. This module
// never changes source ordinals or IDs; callers use readingOrder for display only.
import rules from './episode_reading_order_rules.json' with { type: 'json' };

const normalize = value => String(value || '').normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase();
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const explicit = new RegExp(`${rules.numberPattern}\\s*(${rules.units})`, 'g');
const ending = new RegExp(`${rules.numberPattern}\\s*(?:화|권|회|장)?\\s*(?:\\(완결\\)|완결|完)?$`);
const markers = new RegExp(`(?:^|[\\s(])(${rules.extraGroups.flat().map(escape).join('|')})(?=$|[\\s)0-9])`);

function classifier(workTitle) {
    const work = normalize(workTitle);
    const prefix = work ? new RegExp(`^${[...work.replace(/\s/g, '')].map(escape).join('\\s*')}(?=$|[\\s(0-9:：-])\\s*`) : null;
    return record => {
        let text = normalize(record.sourceTitle || record.displayTitle);
        if (normalize(text).replace(/\s/g, '') === work.replace(/\s/g, '')) text = '';
        else {
            text = text.split(/…|\.{3}/).at(-1).trim();
            if (prefix) text = text.replace(prefix, '').trim();
        }
        const unknown = warning => ({group:'source', warning, unit:'', key:null});
        if (!text || record.numberInferred) return unknown('unnumbered');
        if (/[0-9]+(?:\.[0-9]+)?\s*[~～–—]\s*[0-9]+/.test(text)
            || /[0-9]+\s*(?:부|시즌)/.test(text)) return unknown('ambiguous_context');
        const marker = text.match(markers);
        const matches = [...text.matchAll(explicit)];
        const before = marker ? matches.filter(m => m.index < marker.index) : [];
        let group = 'main', extra = -1, attached = 0, match;
        if (marker && before.length === 1) {
            match = before[0]; attached = 1; group = 'attached';
        } else if (marker && before.length === 0) {
            extra = rules.extraGroups.findIndex(names => names.includes(marker[1]));
            match = text.slice(marker.index + marker[0].length).trim().match(ending);
            if (!match || match.index !== 0) return unknown('unnumbered_extra');
            group = 'extra';
        } else if (marker || matches.length > 1) return unknown('ambiguous_number');
        else match = matches[0] || text.match(ending);
        if (!match) return unknown('unnumbered');
        const value = Number(`${match[1]}.${match[2] || '0'}`), part = Number(match[3] || 0);
        if (!Number.isFinite(value) || value > 1e9 || part > 1e9) return unknown('number_limit');
        return {group, extra, warning:'', unit:match[4] || '', key:[value, part, attached]};
    };
}

export function assignReadingOrder(records, workTitle = '') {
    const classify = classifier(workTitle);
    const rows = records.map((record, index) => ({record, index, ...classify(record)}));
    const source = [...rows].sort((a,b) => Number(a.record.number) - Number(b.record.number) || a.index-b.index);
    const units = new Set(rows.filter(r => r.group !== 'extra' && r.unit).map(r => r.unit));
    for (const row of rows) {
        if (!row.unit && row.key && row.group !== 'extra') {
            if (units.size > 1) { row.key=null; row.warning='mixed_units'; row.group='source'; }
            else row.unit = [...units][0] || '';
        }
    }
    const compare = (a,b) => {
        for (let i=0; i<3; i++) if (a.key[i] !== b.key[i]) return a.key[i]-b.key[i];
        return Number(a.record.number)-Number(b.record.number) || a.index-b.index;
    };
    const main = source.filter(r => r.group !== 'extra'), ordered = [], run = [];
    const flush = () => { ordered.push(...run.sort(compare)); run.length=0; };
    for (const row of main) {
        // Unnumbered/ambiguous entries anchor both neighbouring runs. Mixed units
        // also form separate runs; never guess whether volume 2 means chapter 2.
        if (!row.key) { flush(); ordered.push(row); }
        else { if (run.length && run[0].unit !== row.unit) flush(); run.push(row); }
    }
    flush();
    ordered.push(...source.filter(r => r.group === 'extra').sort((a,b) => a.extra-b.extra || compare(a,b)));
    const slots = source.map(r => Number(r.record.number));
    const uniqueSlots = slots.every(n => Number.isSafeInteger(n) && n > 0) && new Set(slots).size === slots.length;
    const result = new Array(records.length);
    ordered.forEach((row, index) => {
        result[row.index] = {...row.record, readingOrder:uniqueSlots ? slots[index] : index+1,
            readingOrderVersion:rules.version, readingGroup:row.group, readingOrderWarning:row.warning};
    });
    return result;
}
