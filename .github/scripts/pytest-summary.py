"""Write pass/fail/skip counts (and skip reasons) of a pytest JUnit report to the
GitHub job summary. Used by .github/workflows/ci.yml. No secrets involved.

usage: python3 .github/scripts/pytest-summary.py <junit.xml> "<title>" ["<note>"]
"""
import collections
import os
import sys
import xml.etree.ElementTree as ET


def summarise(path: str) -> dict:
    cases = list(ET.parse(path).getroot().iter('testcase'))
    skipped = [c for c in cases if c.find('skipped') is not None]
    failed = [c for c in cases if c.find('failure') is not None or c.find('error') is not None]
    reasons = collections.Counter((c.find('skipped').get('message') or '').strip()[:140] for c in skipped)
    return {'passed': len(cases) - len(skipped) - len(failed), 'failed': len(failed),
            'skipped': len(skipped), 'skip_reasons': reasons.most_common(),
            'failed_ids': [f"{c.get('classname')}::{c.get('name')}" for c in failed]}


def main(argv: list[str]) -> None:
    path, title = argv[1], argv[2]
    note = argv[3] if len(argv) > 3 else ''
    lines = [f'### {title}', '']
    if not os.path.exists(path):
        lines.append('No JUnit report: pytest did not run.')
    else:
        s = summarise(path)
        lines += ['| passed | failed | skipped |', '|---|---|---|',
                  f"| {s['passed']} | {s['failed']} | {s['skipped']} |", '']
        if note:
            lines += [note, '']
        lines += [f'- {n} skipped: {reason}' for reason, n in s['skip_reasons']]
        lines += [f'- FAILED {t}' for t in s['failed_ids'][:50]]
    text = '\n'.join(lines) + '\n'
    target = os.environ.get('GITHUB_STEP_SUMMARY')
    if target:
        with open(target, 'a') as fh:
            fh.write(text)
    print(text)


if __name__ == '__main__':
    main(sys.argv)
