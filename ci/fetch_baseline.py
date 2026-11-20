"""Fetch the live snapshot for monotonic-history checks and banner retention."""
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request


FETCH_ATTEMPTS = 5
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}


def retry_delay(error, attempt):
    delay = 2 ** (attempt - 1)
    headers = getattr(error, 'headers', None)
    retry_after = headers.get('Retry-After') if headers else None
    if retry_after:
        try:
            seconds = int(retry_after)
        except ValueError:
            try:
                seconds = parsedate_to_datetime(retry_after).timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                seconds = 0
        delay = max(delay, seconds)
    return min(delay, 30)


def fetch(url, limit):
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(limit + 1)
        except (urllib.error.URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
                if error.code not in RETRYABLE_HTTP:
                    raise
            if attempt == FETCH_ATTEMPTS:
                raise RuntimeError(
                    f'Failed to fetch published baseline {url} after {attempt} attempts: {error}'
                ) from error
            delay = retry_delay(error, attempt)
            print(f'Baseline download failed ({error}); retrying {url} '
                  f'in {delay:g}s (attempt {attempt + 1}/{FETCH_ATTEMPTS})',
                  file=sys.stderr, flush=True)
            time.sleep(delay)
            continue
        if len(data) > limit:
            raise ValueError(f'Published baseline exceeds the supported size: {url}')
        return data


def main():
    base = os.environ['PAGES_URL'].rstrip('/')
    if not base.startswith('https://'):
        raise ValueError('Expected HTTPS Pages URL')
    root = Path('baseline'); (root/'banners').mkdir(parents=True,exist_ok=True)
    raw = fetch(base+'/data.json',64*1024*1024)
    data = json.loads(raw)
    (root/'data.json').write_bytes(raw)
    # Fetch only missing banner sources, not every historical image on each upload.
    profile = os.environ['UPLOAD_PROFILE']
    mapping={}
    for p in (Path('upload-data')/'profiles'/profile/'songs').glob('*.json'):
        m=json.loads(p.read_text());mapping[m.get('dir')]=m.get('banner')
    for song in data.get('songs',[]):
        name=song.get('banner','')
        if mapping.get(song.get('dir')) or not re.fullmatch(r'banners/[0-9a-f]+\.png',name):
            continue
        dest=root/name
        if not dest.exists(): dest.write_bytes(fetch(base+'/'+name,256*1024))

if __name__ == '__main__':
    main()
