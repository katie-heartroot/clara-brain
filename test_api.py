import os, json, urllib.request, urllib.error
key = os.environ.get('ANTHROPIC_API_KEY', '')
print(f"Key present: {bool(key)}, length: {len(key)}")
payload = json.dumps({
    'model': 'claude-sonnet-4-20250514',
    'max_tokens': 100,
    'system': 'You are Clara. Say hello.',
    'messages': [{'role': 'user', 'content': 'Hi'}]
}).encode()
req = urllib.request.Request(
    'https://api.anthropic.com/v1/messages',
    data=payload,
    headers={
        'Content-Type': 'application/json',
        'x-api-key': key,
        'anthropic-version': '2023-06-01'
    },
    method='POST'
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print('OK:', r.read().decode()[:300])
except urllib.error.HTTPError as e:
    print(f'ERROR {e.code}:', e.read().decode()[:500])
except Exception as e:
    print('EXC:', e)
