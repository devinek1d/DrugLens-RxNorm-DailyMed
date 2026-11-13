"""Tiny requests adapter with timeouts, retries and bounded response sizes."""
from __future__ import annotations
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class ApiError(Exception):
    """Recoverable upstream error shown explicitly in the UI."""

class ApiClient:
    def __init__(self, session=None):
        if session is None:
            session = requests.Session()
            retry = Retry(total=2, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=['GET'])
            session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session = session
        self.session.headers.update({'User-Agent': 'DrugLens-ResearchDemo/1.0 (NLM public data; Streamlit)', 'Accept': 'application/json, application/xml, text/xml'})
        key = os.environ.get('UMLS_API_KEY', '').strip()
        self.rx_headers = {'Authorization': 'Bearer ' + key} if key else {}

    def get_json(self, url: str, params: dict | None = None, *, rxnorm=False) -> dict:
        try:
            response = self.session.get(url, params=params, timeout=(5, 24), headers=self.rx_headers if rxnorm else None)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('Ответ должен быть JSON-объектом')
            return data
        except (requests.RequestException, ValueError) as exc:
            raise ApiError(f'Ошибка API {url.split("/")[2]}: {exc}') from exc

    def get_xml(self, url: str) -> bytes:
        try:
            response = self.session.get(url, timeout=(5, 30))
            response.raise_for_status()
            if len(response.content) > 7_000_000:
                raise ApiError('XML-инструкция слишком велика для демоверсии (> 7 MB)')
            return response.content
        except requests.RequestException as exc:
            raise ApiError(f'Ошибка получения инструкции: {exc}') from exc

