"""Fetch the live snapshot for monotonic-history checks and banner retention."""
import json
import os
from pathlib import Path
import re
import urllib.request


def fetch(url, limit):
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(limit+1)
    if len(data) > limit:
        raise ValueError('Published baseline exceeds the supported size')
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
