"""Extract source text including nested HWPX text markers; never execute content."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


def local_name(node):
    return node.tag.rsplit('}', 1)[-1]


def text(node):
    return ''.join(''.join(n.itertext()) for n in node.iter() if local_name(n) == 't')


def extract(path: Path) -> str:
    sections = []
    with ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not (name.startswith('Contents/section') and name.endswith('.xml')):
                continue
            root = ET.fromstring(archive.read(name))
            sections.append(f'[{name}]')
            for paragraph in root:
                if local_name(paragraph) != 'p':
                    continue
                tables = [n for n in paragraph.iter() if local_name(n) == 'tbl']
                if tables:
                    for table in tables:
                        sections.append('[표]')
                        for row in table:
                            if local_name(row) == 'tr':
                                sections.append(' | '.join(text(c) for c in row if local_name(c) == 'tc'))
                else:
                    sections.append(text(paragraph))
    return '\n'.join(sections)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(extract(args.input), encoding='utf-8')
    args.output.with_suffix('.source.json').write_text(json.dumps({
        'filename':args.input.name,
        'sha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),
        'format':'HWPX / Contents/section*.xml',
        'academic_year':2026,
        'student_grade':2,
    },ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
