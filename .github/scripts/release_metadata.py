"""Read release tags and advance only the selected environment's version."""

import argparse
import json
import os
from pathlib import Path
import re


def metadata(path, environment):
    if environment not in {'dev', 'qa', 'prod'}:
        raise ValueError('Release environment must be dev, qa, or prod')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['name'] != 'aws-monitor':
        raise ValueError('Application metadata must identify aws-monitor')
    version = data['version'][environment]
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Release version must have the form major.minor.patch')
    return data, version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'bump'])
    parser.add_argument('--path', type=Path, default=Path('.app-info.json'))
    args = parser.parse_args()
    environment = os.environ['RELEASE_ENV']
    data, version = metadata(args.path, environment)
    if args.command == 'prepare':
        suffix = '' if environment == 'prod' else f'-{environment}'
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write(f'tag={version}{suffix}\nlatest=latest{suffix}\n')
    else:
        major, minor, patch = map(int, version.split('.'))
        data['version'][environment] = f'{major}.{minor}.{patch + 1}'
        args.path.write_text(json.dumps(data, indent=4) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
