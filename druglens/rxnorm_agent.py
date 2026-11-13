"""Agent A: RxNorm drug product and ingredient normalization."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from .client import ApiClient

ROOT = 'https://rxnav.nlm.nih.gov/REST'
PRODUCT_TYPES = {'SCD', 'SBD', 'GPCK', 'BPCK'}

@dataclass(frozen=True)
class Concept:
    rxcui: str
    name: str
    tty: str
    synonym: str = ''

    def as_dict(self):
        return asdict(self)


def _concepts(payload: dict, group_name: str) -> list[Concept]:
    found, seen = [], set()
    for group in (payload.get(group_name) or {}).get('conceptGroup', []) or []:
        for item in group.get('conceptProperties', []) or []:
            code = str(item.get('rxcui') or '').strip()
            if code and code not in seen and code.isdigit():
                found.append(Concept(code, str(item.get('name') or ''), str(item.get('tty') or group.get('tty') or ''), str(item.get('synonym') or '')))
                seen.add(code)
    return found

class RxNormAgent:
    def __init__(self, client: ApiClient | None = None):
        self.client = client or ApiClient()

    def find(self, query: str, limit: int = 35) -> dict:
        query = ' '.join(query.split()).strip()
        if not query:
            return {'query': '', 'concepts': [], 'method': 'empty'}
        data = self.client.get_json(f'{ROOT}/drugs.json', {'name': query}, rxnorm=True)
        products = [c for c in _concepts(data, 'drugGroup') if c.tty in PRODUCT_TYPES]
        if products:
            # Exact branded/ingredient names should appear before distant lookalikes.
            needle = query.casefold()
            products.sort(key=lambda c: (0 if needle in (c.name + ' ' + c.synonym).casefold() else 1, 0 if c.tty in ('SBD','SCD') else 1, c.name.casefold()))
            return {'query': query, 'concepts': [c.as_dict() for c in products[:limit]], 'method': 'drug-name'}
        # When no drug products match, offer direct RxCUI normalization.
        exact = self.client.get_json(f'{ROOT}/rxcui.json', {'name': query, 'search': 2}, rxnorm=True)
        ids = (exact.get('idGroup') or {}).get('rxnormId', []) or []
        method = 'normalized-name'
        if not ids:
            approx = self.client.get_json(f'{ROOT}/approximateTerm.json', {'term': query, 'maxEntries': 4}, rxnorm=True)
            ids = [x.get('rxcui') for x in (approx.get('approximateGroup') or {}).get('candidate', []) or []]
            method = 'approximate'
        concepts = []
        for code in dict.fromkeys(str(x) for x in ids if str(x).isdigit()):
            props = (self.client.get_json(f'{ROOT}/rxcui/{code}/properties.json', rxnorm=True).get('properties') or {})
            if props.get('rxcui'):
                concepts.append(Concept(str(props['rxcui']), str(props.get('name') or query), str(props.get('tty') or 'UNKNOWN')).as_dict())
            if len(concepts) >= min(limit, 4):
                break
        return {'query': query, 'concepts': concepts, 'method': method}

    def ingredients(self, rxcui: str) -> list[dict]:
        if not str(rxcui).isdigit():
            return []
        data = self.client.get_json(f'{ROOT}/rxcui/{rxcui}/related.json', {'tty': 'IN PIN MIN'}, rxnorm=True)
        concepts = _concepts(data, 'relatedGroup')
        # Prefer IN concepts over PIN; use MIN only if no more precise info.
        singles = [c for c in concepts if c.tty == 'IN']
        if singles:
            chosen = singles
        else:
            chosen = [c for c in concepts if c.tty in {'PIN', 'MIN'}]
        return [c.as_dict() for c in chosen]

