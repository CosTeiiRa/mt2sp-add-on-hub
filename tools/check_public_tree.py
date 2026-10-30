"""Audit the Git index against an explicit public file list and privacy patterns.

No matched content is printed. This is a review aid, not a secret detector guarantee.
"""
import argparse
import re
import subprocess
from pathlib import PurePosixPath


def git(*args):
    return subprocess.check_output(['git', *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-term', action='append', default=[])
    parser.add_argument('--base', help='Also inspect outgoing commit metadata since this ref')
    args = parser.parse_args()
    paths = git('ls-files', '-z').decode().split('\0')[:-1]
    allowed = set(git('show', ':config/public-files.txt').decode().splitlines())
    failures = []
    if set(paths) != allowed:
        failures.append('Tracked files differ from the public allowlist.')
    patterns = {
        'personal-path': r'(?i)(?:[a-z]:[\\/](?:users|documents and settings)[\\/]|/(?:Users|home)/[A-Za-z0-9_.-]+)',
        'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'github-token': r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
        'private-network': r'\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)\b',
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
    }
    for path in paths:
        raw = git('show', ':' + path)
        if len(raw) > 2 * 1024 * 1024 or b'\x00' in raw:
            failures.append(path + ': binary or oversized content')
            continue
        try:
            text = raw.decode('utf-8')
        except UnicodeError:
            failures.append(path + ': non UTF-8 content')
            continue
        for label, pattern in patterns.items():
            matches = re.findall(pattern, text)
            if label == 'email':
                matches = [email for email in matches if not
                           (email.endswith('@users.noreply.github.com') or email == 'noreply@github.com')]
            if matches:
                failures.append(path + ': ' + label)
        if any(term.casefold() in text.casefold() for term in args.private_term if term):
            failures.append(path + ': private term')
        if path.endswith('.md'):
            if len(re.findall(r'^```', text, re.M)) % 2:
                failures.append(path + ': unbalanced fence')
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                if target.startswith(('https://', 'http://', '#')):
                    continue
                parts = list(PurePosixPath(path).parent.parts)
                for part in target.split('#')[0].split('/'):
                    if part == '..':
                        if parts:
                            parts.pop()
                    elif part not in ('', '.'):
                        parts.append(part)
                if '/'.join(parts) not in allowed:
                    failures.append(path + ': missing relative link')
    if args.base:
        records = git('log', args.base + '..HEAD', '--format=%ae%x09%ce%x09%B%x00').decode()
        for record in records.split('\0'):
            if not record.strip():
                continue
            author, committer, message = record.strip().split('\t', 2)
            if not all(email.endswith('@users.noreply.github.com') or email == 'noreply@github.com'
                       for email in (author, committer)):
                failures.append('Outgoing commit uses an unapproved email identity.')
            if any(term.casefold() in message.casefold() for term in args.private_term if term):
                failures.append('Outgoing commit message contains a private term.')
    if failures:
        for failure in failures:
            print('FAIL: ' + failure)
        return 1
    print(f'PASS: {len(paths)} tracked text files match the publication allowlist; selected privacy and link checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
