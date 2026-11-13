"""Orchestrator + verification/comparison agents. No medical judgments."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from .client import ApiClient, ApiError
from .rxnorm_agent import RxNormAgent
from .dailymed_agent import DailyMedAgent, SECTION_TITLES

class Orchestrator:
    def __init__(self, client: ApiClient | None = None):
        client = client or ApiClient()
        self.rx = RxNormAgent(client)
        self.dm = DailyMedAgent(client)

    def find(self, term: str) -> dict:
        """Independent agents run concurrently; partial outage remains visible."""
        term = ' '.join(term.split()).strip()[:100]
        result = {'term': term, 'rxnorm': {'query': term, 'concepts': [], 'method': 'unavailable'}, 'by_name': [], 'errors': []}
        if not term:
            return result
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = {'rxnorm': pool.submit(self.rx.find, term), 'dailymed': pool.submit(self.dm.search, drug_name=term)}
            for name, future in jobs.items():
                try:
                    value = future.result()
                    result['rxnorm' if name == 'rxnorm' else 'by_name'] = value
                except (ApiError, ValueError) as exc:
                    result['errors'].append(f'{name}: {exc}')
        return result

    def detail(self, term: str, concept: dict | None, general_labels: list[dict]) -> dict:
        result = {'ingredient_concepts': [], 'labels': general_labels, 'match': 'по названию', 'errors': []}
        if concept and concept.get('rxcui'):
            rxcui = concept['rxcui']
            # The selected product RxCUI makes the second source more precise.
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = {'ingredients': pool.submit(self.rx.ingredients, rxcui), 'labels': pool.submit(self.dm.search, rxcui=rxcui)}
                for name, future in jobs.items():
                    try:
                        value = future.result()
                        if name == 'ingredients':
                            result['ingredient_concepts'] = value
                        elif value:
                            result['labels'] = value
                            result['match'] = 'точный RxCUI'
                        else:
                            result['match'] = 'по названию (по RxCUI не найдено)'
                    except (ApiError, ValueError) as exc:
                        result['errors'].append(f'{name}: {exc}')
                        if name == 'labels':
                            result['match'] = 'по названию (RxCUI-поиск недоступен)'
        return result

    def load_label(self, label: dict | None) -> dict:
        if label is None:
            return {'sections': {}, 'titles': {}, 'error': 'Не выбрана инструкция'}
        try:
            data = self.dm.fetch_sections(label['setid'])
            return {**data, 'error': ''}
        except (ApiError, ValueError, Exception) as exc:
            # UI must preserve label link even when XML cannot be read.
            return {'sections': {}, 'titles': {}, 'error': f'Не удалось прочитать XML SPL: {exc}'}

class VerificationAgent:
    @staticmethod
    def ingredient_relation(ingredients_a: list[dict], ingredients_b: list[dict]) -> dict:
        a = {str(x['rxcui']): x['name'] for x in ingredients_a if x.get('rxcui')}
        b = {str(x['rxcui']): x['name'] for x in ingredients_b if x.get('rxcui')}
        if not a or not b:
            status = 'Невозможно установить по найденным данным RxNorm'
        elif set(a) == set(b):
            status = 'Совпадают идентификаторы действующих веществ RxNorm'
        elif set(a) & set(b):
            status = 'Есть общие, но не все действующие вещества'
        else:
            status = 'Идентификаторы действующих веществ не совпадают'
        return {'status': status, 'common': [a[k] for k in a.keys() & b.keys()], 'left_only': [a[k] for k in a.keys() - b.keys()], 'right_only': [b[k] for k in b.keys() - a.keys()]}

    @staticmethod
    def compare_sections(left: dict, right: dict) -> list[dict]:
        a, b = left.get('sections', {}), right.get('sections', {})
        rows = []
        for key, title in SECTION_TITLES.items():
            ta, tb = a.get(key, ''), b.get(key, '')
            if ta and tb:
                status = 'Тексты совпадают' if ' '.join(ta.lower().split()) == ' '.join(tb.lower().split()) else 'Тексты различаются'
            elif ta:
                status = 'Есть только слева в извлечённых данных'
            elif tb:
                status = 'Есть только справа в извлечённых данных'
            else:
                status = 'В обеих инструкциях раздел не извлечён'
            rows.append({'Раздел': title, 'Статус': status, 'Слева': ta, 'Справа': tb})
        return rows

    @classmethod
    def report(cls, left: dict, right: dict):
        return {
            'generated_utc': datetime.now(timezone.utc).isoformat(),
            'left': left, 'right': right,
            'ingredient_check': cls.ingredient_relation(left.get('ingredients', []), right.get('ingredients', [])),
            'section_comparison': cls.compare_sections(left.get('document', {}), right.get('document', {})),
            'limitations': 'Текстовое сравнение разделов не устанавливает терапевтическую эквивалентность, клинические преимущества или безопасность замены препаратов.',
        }

