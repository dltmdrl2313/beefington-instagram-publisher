"""Publish prepared JPEGs. No AI APIs, browser cookies, or paid services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
HOURS = (9, 12, 15, 18, 21)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return parsed


def choose(queue, ledger, now):
    """Never catch up in bursts or publish a later/expired queue item."""
    candidates = []
    ids, slots = set(), set()
    for item in queue:
        identity = item['id']
        due = timestamp(item['scheduled_at']).astimezone(KST)
        if identity in ids or due.isoformat() in slots:
            raise ValueError('Duplicate queue id or posting slot')
        ids.add(identity)
        slots.add(due.isoformat())
        if due.hour not in HOURS or due.minute or due.second or due.microsecond:
            raise ValueError('Only 09/12/15/18/21 KST posting slots are allowed')
        if not item.get('approved') or identity in ledger:
            continue
        if timedelta(0) <= now - due <= timedelta(minutes=90):
            sources = item.get('sources', [])
            if len(sources) < 1:
                raise ValueError('A verified trend source is required')
            for source in sources:
                when = timestamp(source['observed_at'])
                if not timedelta(0) <= now - when <= timedelta(days=7):
                    raise ValueError('Trend evidence is outside the last 7 days')
                if not source['url'].startswith('https://'):
                    raise ValueError('Trend source must use HTTPS')
            if not 1 <= len(item['caption']) <= 2200:
                raise ValueError('Caption must contain 1–2200 characters')
            path = (ROOT / item['image']).resolve()
            if ROOT not in path.parents or not path.is_file():
                raise ValueError('Image must be a file inside this repository')
            data = path.read_bytes()
            if not data.startswith(b'\xff\xd8\xff') or len(data) > 8_000_000:
                raise ValueError('Use a JPEG smaller than 8 MB')
            digest = hashlib.sha256(data).hexdigest()
            if digest != item['sha256']:
                raise ValueError('Image checksum mismatch')
            if any(old.get('sha256') == digest for old in ledger.values()):
                raise ValueError('This image was already submitted')
            candidates.append(item)
    return max(candidates, key=lambda item: timestamp(item['scheduled_at']), default=None)


def request_json(method, url, token, body=None):
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
               'User-Agent': 'BeefingtonPreparedPublisher/1.0'}
    encoded = None
    if body is not None:
        encoded = urlencode(body).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    try:
        with urlopen(Request(url, data=encoded, headers=headers, method=method), timeout=45) as response:
            return json.load(response)
    except HTTPError as error:
        # Never print response bodies, headers, credentials, or token-bearing URLs.
        raise RuntimeError(f'API request failed with HTTP {error.code}') from None


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Unable to persist posting state; stopped to avoid duplicates')
    return result.stdout.strip()


def save(ledger):
    (ROOT / 'state.json').write_text(json.dumps(ledger, indent=2) + '\n', encoding='utf-8')
    git('add', 'state.json')
    git('commit', '-m', 'Record publisher state [skip ci]')
    git('push', 'origin', 'HEAD:main')


def summary(message):
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write(message + '\n')


def run(publish=False, now=None):
    now = now or datetime.now(KST)
    queue = json.loads((ROOT / 'queue.json').read_text(encoding='utf-8'))
    ledger = json.loads((ROOT / 'state.json').read_text(encoding='utf-8'))
    if any(entry['status'] in ('creating', 'ready', 'publishing', 'uncertain') for entry in ledger.values()):
        raise RuntimeError('A prior request has an uncertain outcome. Inspect Instagram and state.json before resuming.')
    item = choose(queue, ledger, now)
    if not item:
        summary('No approved prepared post is due. Nothing was published.')
        return
    if not publish:
        summary('Validation passed for prepared post: ' + item['id'] + '. No external requests made.')
        return
    if os.environ.get('PUBLISH_ENABLED') != 'true':
        raise RuntimeError('Publishing is disabled. Set PUBLISH_ENABLED=true only after authentication tests.')
    token = os.environ.get('IG_ACCESS_TOKEN', '')
    user_id = os.environ.get('IG_USER_ID', '')
    if not token or not user_id.isdigit():
        raise RuntimeError('Configure IG_ACCESS_TOKEN and numeric IG_USER_ID in GitHub Secrets')
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    gh_token = os.environ.get('GITHUB_TOKEN', '')
    if repository.count('/') != 1 or not gh_token:
        raise RuntimeError('Run from GitHub Actions with GITHUB_TOKEN')
    # Public standard Linux runners only. Refuse private repos rather than risking billing.
    metadata = request_json('GET', 'https://api.github.com/repos/' + repository, gh_token)
    if metadata.get('private') is not False:
        raise RuntimeError('This zero-additional-cost workflow requires a public repository')
    version = os.environ.get('IG_API_VERSION', 'v25.0')
    if not version.startswith('v') or not version[1:].replace('.', '').isdigit():
        raise ValueError('Invalid Instagram API version')
    base = 'https://graph.instagram.com/' + version
    profile = request_json('GET', base + '/me?fields=user_id,username', token)
    if profile.get('username', '').lower() != 'mr.sirbeefington':
        raise RuntimeError('Token is not for @mr.sirbeefington. Publishing stopped.')
    if str(profile.get('user_id', '')) != user_id:
        raise RuntimeError('IG_USER_ID does not match the authenticated account')
    # Store intent durably BEFORE asking Meta to create/publish. A failed or ambiguous
    # request remains blocked for human reconciliation; it is never blindly retried.
    entry = {'status': 'creating', 'scheduled_at': item['scheduled_at'],
             'sha256': item['sha256'], 'caption': item['caption'], 'at': now.isoformat()}
    ledger[item['id']] = entry
    save(ledger)
    image_path = quote(item['image'], safe='/')
    commit = git('rev-parse', 'HEAD')
    image_url = f'https://raw.githubusercontent.com/{repository}/{commit}/{image_path}'
    try:
        created = request_json('POST', base + '/' + user_id + '/media', token,
                               {'image_url': image_url, 'caption': item['caption'], 'is_ai_generated': 'true'})
        container = created['id']
        entry.update(status='ready', container_id=container)
        save(ledger)
        for _ in range(18):
            status = request_json('GET', base + '/' + container + '?fields=status_code', token)['status_code']
            if status == 'FINISHED':
                break
            if status in ('ERROR', 'EXPIRED'):
                raise RuntimeError('Instagram rejected the media container')
            time.sleep(5)
        else:
            raise RuntimeError('Instagram media preparation timed out')
        entry['status'] = 'publishing'
        save(ledger)
        published = request_json('POST', base + '/' + user_id + '/media_publish', token,
                                 {'creation_id': container})
        entry.update(status='published', media_id=published['id'])
        save(ledger)
    except Exception:
        entry['status'] = 'uncertain'
        save(ledger)
        raise
    details = request_json('GET', base + '/' + entry['media_id'] + '?fields=permalink', token)
    entry['permalink'] = details['permalink']
    save(ledger)
    summary('Published: ' + details['permalink'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    try:
        run(args.publish)
    except Exception as error:
        # Only our own sanitized messages, never urllib exceptions (may contain secrets).
        if isinstance(error, (RuntimeError, ValueError)):
            print('Stopped: ' + str(error), file=sys.stderr)
        else:
            print('Stopped: unexpected error (' + type(error).__name__ + '). No automatic retry.', file=sys.stderr)
        sys.exit(1)
