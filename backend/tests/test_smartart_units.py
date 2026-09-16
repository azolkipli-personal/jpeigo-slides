"""Unit checks for the shared SmartArt node enumeration (app/core/smartart.py).

Run: backend/venv/bin/python tests/test_smartart_units.py

Covers the failure the shared module exists to prevent: extraction and injection
numbering *different* node lists, so a translation written to ordinal i lands in a
node that held different text — silently, because a wrong write is not an error.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lxml import etree

from app.core.smartart import (
    find_diagram_part,
    is_smartart_graphic_frame,
    iter_text_nodes,
)
from app.core.extractor import extract_smartart_text, generate_run_id
from app.core.injector import inject_smartart_text
from app.models import TranslatedRun

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
DGM = 'http://schemas.openxmlformats.org/drawingml/2006/diagram'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

# Empty and whitespace-only points sit between real ones: that is exactly what
# made the two sides' indices diverge on a real client deck.
DIAGRAM = f'''<dgm:dataModel xmlns:dgm="{DGM}" xmlns:a="{A}" xmlns:r="{R}">
  <dgm:ptLst>
    <dgm:pt modelId="0"><dgm:t><a:p><a:r><a:t>Chilli harvest</a:t></a:r></a:p></dgm:t></dgm:pt>
    <dgm:pt modelId="1"><dgm:t><a:p><a:r><a:t>   </a:t></a:r></a:p></dgm:t></dgm:pt>
    <dgm:pt modelId="2"><dgm:t><a:p><a:r><a:t>Quality control</a:t></a:r></a:p></dgm:t>
      <dgm:pt modelId="2a"><dgm:t><a:p><a:r><a:t>Nested point</a:t></a:r></a:p></dgm:t></dgm:pt>
    </dgm:pt>
    <dgm:pt modelId="3"><dgm:t><a:p><a:r><a:t></a:t></a:r><a:r><a:t>Shipping</a:t></a:r></a:p></dgm:t></dgm:pt>
  </dgm:ptLst>
</dgm:dataModel>'''
EXPECTED = ['Chilli harvest', 'Quality control', 'Nested point', 'Shipping']

FRAME = f'''<p:graphicFrame xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}" xmlns:dgm="{DGM}">
  <a:graphic><a:graphicData uri="{DGM}"><dgm:relIds r:dm="rId1" r:lo="rId2"/></a:graphicData></a:graphic>
</p:graphicFrame>'''
TABLE_FRAME = f'''<p:graphicFrame xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}">
  <a:graphic><a:graphicData uri="{A}/table"><a:tbl/></a:graphicData></a:graphic>
</p:graphicFrame>'''


class FakePart:
    """Stands in for the python-pptx part objects the real code touches."""

    def __init__(self, blob):
        self.blob = blob
        self._blob = None

    def related_part(self, rel_id):
        return self


class FakeShape:
    def __init__(self, xml, part):
        self._element = etree.fromstring(xml)
        self.part = part


def make_run(ordinal, original, translated, shape_idx='3'):
    return TranslatedRun(
        run_id=generate_run_id(2, f'smartart_{shape_idx}', 0, ordinal),
        original_text=original,
        translated_text=translated,
        source_language='ja',
        target_language='en',
        model_used='unit-test',
    )


def written_texts(part):
    """Node texts as they stand now: the written blob if any, else the original."""
    blob = part._blob if part._blob is not None else part.blob
    root = etree.fromstring(blob)
    return [(t.text or '') for t in iter_text_nodes(root)]


results = []


def check(name, ok, detail=''):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ''))


# 1. The canonical list: document order, empties (incl. whitespace-only) skipped.
nodes = iter_text_nodes(etree.fromstring(DIAGRAM))
check('enumerator keeps order and skips empty nodes', [n.text for n in nodes] == EXPECTED,
      f"got {[n.text for n in nodes]}")

# 2. Extraction numbers every node 0..n-1. Before the fix this returned no runs
#    at all (the append sat after a `continue`), so SmartArt shipped untranslated.
part = FakePart(DIAGRAM.encode())
shape = FakeShape(FRAME, part)
runs = extract_smartart_text(shape, part, 2, 3)
check('extraction returns one run per node', len(runs) == len(EXPECTED), f"got {len(runs)}")
check('extraction ordinals are 0-based and complete',
      [int(r.run_id.split('_')[-2]) for r in runs] == list(range(len(EXPECTED))),
      f"got {[r.run_id for r in runs]}")
check('extraction carries the node text', [r.text for r in runs] == EXPECTED)

# 3. Injection writes each translation into the node the extractor named — the
#    alignment proof, across the empty and whitespace-only nodes.
part = FakePart(DIAGRAM.encode())
shape = FakeShape(FRAME, part)
tr = [make_run(i, text, f"TR{i}:{text}") for i, text in enumerate(EXPECTED)]
failed = inject_smartart_text(shape, tr, 2)
check('injection reports no failures', failed == [], f"failed {len(failed)}")
check('injection lands in the matching node',
      written_texts(part) == [f"TR{i}:{t}" for i, t in enumerate(EXPECTED)],
      f"got {written_texts(part)}")
check('injection writes the diagram part back', part._blob is not None)

# 4. Divergence guard: a run whose original text is not the node's text is
#    refused, not written, and reported.
part = FakePart(DIAGRAM.encode())
shape = FakeShape(FRAME, part)
bad = make_run(1, 'text from another node', 'SHOULD NOT LAND')
failed = inject_smartart_text(shape, [bad], 2)
check('divergence is reported as a failure', failed == [bad])
check('divergence leaves the node untouched', written_texts(part) == EXPECTED)

# 5. Out-of-range ordinal fails instead of clamping onto a neighbour.
part = FakePart(DIAGRAM.encode())
shape = FakeShape(FRAME, part)
oob = make_run(99, EXPECTED[0], 'SHOULD NOT LAND')
check('out-of-range ordinal fails', inject_smartart_text(shape, [oob], 2) == [oob])
check('out-of-range writes nothing', part._blob is None)

# 6. Group-nested shapes put an extra underscore in the run id ("smartart.3.1"):
#    the ordinal must still be read from the second-to-last slot.
part = FakePart(DIAGRAM.encode())
shape = FakeShape(FRAME, part)
group_run = make_run(2, EXPECTED[2], 'GROUP PATH OK', shape_idx='3_1')
check('group-path run id resolves the ordinal',
      'smartart.3.1' in group_run.run_id and inject_smartart_text(shape, [group_run], 2) == [])
check('group-path run writes the right node',
      written_texts(part)[2] == 'GROUP PATH OK', f"got {written_texts(part)}")

# 7. Non-SmartArt frames: detected as such, and routed runs are reported rather
#    than dropped (a silent no-op is how untranslated text shipped unnoticed).
table_part = FakePart(b'<a:tbl xmlns:a="%s"/>' % A.encode())
table_shape = FakeShape(TABLE_FRAME, table_part)
check('table frame is not detected as SmartArt', not is_smartart_graphic_frame(table_shape))
check('diagram frame is detected as SmartArt', is_smartart_graphic_frame(shape))
check('table frame yields no diagram part', find_diagram_part(table_shape) == (None, None))

runs_for_table = [make_run(0, EXPECTED[0], 'x')]
check('runs routed to a non-diagram frame are reported',
      inject_smartart_text(table_shape, runs_for_table, 2) == runs_for_table)

passed = sum(1 for _, ok in results if ok)
total = len(results)
print(f"\n{passed}/{total} checks passed")


def test_smartart_units() -> None:
    """The same checks, visible to pytest.

    Without this the file is invisible to `pytest tests/` — and an unguarded
    `sys.exit` at import time aborts the whole collection run, so a broken SmartArt
    module would look like a broken test suite.
    """
    failed = [name for name, ok in results if not ok]
    assert not failed, f'{len(failed)}/{total} SmartArt checks failed: {failed}'


if __name__ == '__main__':
    sys.exit(0 if passed == total else 1)
