"""Verify the explicitly requested destination without printing credentials."""
import json
import subprocess
import requests

credential = subprocess.run(['git','credential','fill'], input='protocol=https\nhost=github.com\n\n',
    text=True, capture_output=True, check=True)
values = dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line)
with requests.Session() as client:
    client.trust_env = False
    client.headers['Authorization'] = 'Bearer '+values['password']
    result = client.get('https://api.github.com/repos/tracecorp24/job_collector',timeout=30)
    result.raise_for_status()
    repo = result.json()
    print(json.dumps({key:repo.get(key) for key in ('full_name','private','default_branch','size','permissions')}))
    if not repo['private']:
        raise SystemExit('Destination must be private for the requested complete upload.')
