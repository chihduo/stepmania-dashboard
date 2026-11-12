"""Resolve only a validated data branch. Workflow/code always comes from main."""
import json
import os
import re
import subprocess
from pathlib import Path


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path]))


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    payload = event.get('client_payload', {})
    branch = os.environ['DATA_BRANCH']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', branch) or branch in ('main','master','gh-pages'):
        raise ValueError('Invalid configured data branch')
    if payload and payload.get('data_branch') != branch:
        raise ValueError('Upload targets a different data branch')
    profile = payload.get('profile') or event.get('inputs', {}).get('profile','')
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', profile):
        raise ValueError('Invalid profile identifier')
    repo = os.environ['GITHUB_REPOSITORY']
    latest = api(f'repos/{repo}/git/ref/heads/{branch}')['object']['sha']
    requested = payload.get('data_revision', latest)
    if not re.fullmatch(r'[0-9a-f]{40}', requested):
        raise ValueError('Invalid data revision')
    if requested != latest:
        comparison = api(f'repos/{repo}/compare/{requested}...{latest}')
        if comparison['status'] not in ('ahead','identical'):
            raise ValueError('Requested revision is not part of the data branch')
    # Build the latest complete tree, including all earlier accepted uploads.
    with open(os.environ['GITHUB_ENV'], 'a') as f:
        f.write(f'DATA_REVISION={latest}\nUPLOAD_PROFILE={profile}\n')

if __name__ == '__main__':
    main()
