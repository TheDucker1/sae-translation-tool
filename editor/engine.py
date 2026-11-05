from __future__ import annotations

import json
import re
import itertools
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDARIES = ['Before start', 'Started', 'Waiting for input', 'Waiting for service',
              'Completed, before dispatch', 'File ready', 'Profile handoff', 'Ended',
              'Restoring resources', 'Slot ready', 'Deferred start']
BRANCHES = {1, 0x65, 0x3F2, 0x3F6, 0x3F8, 0x3FA}


def Session():
    # Lazy import avoids the document/codec/catalog dependency cycle.
    from .runtime import Session as PythonSession
    return PythonSession()


def opcode_names():
    local = Path(__file__).with_name('opcode_names.json')
    if local.is_file():return {int(k,16):v for k,v in json.loads(local.read_text(encoding='utf-8')).items()}
    path = ROOT.parent / 'opcode_inventory.json'
    if not path.is_file():
        return {}
    return {int(r['opcode'], 0): re.sub(r'^\d*Script', '', r.get('rtti_name', ''))
            for r in json.loads(path.read_text(encoding='utf-8'))}


NAMES = opcode_names()


def category(op):
    if op in {0x64, 0x66, 0x12C, 0x12D, 0x12E}: return 'Text'
    if op in BRANCHES or op in {0, 0x2BE, 0x2BF, 0x2C0}: return 'Flow'
    if 0x1F4 <= op <= 0x204 or op == 0x438: return 'Actor'
    if 0x258 <= op <= 0x2C6: return 'Audio / movie'
    if 0x3EA <= op <= 0x400: return 'Gameplay'
    return 'Scene'


def summary(command):
    a = command['args']
    if 'text' in a: return a['text'].replace('\x00', '').replace('\n', ' ')
    if 'choices' in a: return '  /  '.join(c['label'].replace('\x00', '') for c in a['choices'])
    if 'parents' in a: return '  /  '.join(c['label'].replace('\x00', '') for c in a['parents'])
    if 'texts' in a: return '  /  '.join(t.replace('\x00', '') for t in a['texts'])
    return '  ·  '.join(f'{k}: {v}' for k, v in a.items() if k != 'payload_hex') or ('Opaque arguments (raw bytes retained)' if a else 'No executable operands (raw tail retained)')


@dataclass(frozen=True)
class Edge:
    source: int
    target: int
    label: str
    script: int | None = None


class Analysis:
    """Potential edges, not a claim that every runtime guard is satisfiable."""

    def __init__(self, commands, flow=None):
        self.edges: list[Edge] = []
        self.errors: list[str] = []
        self.incoming = {i: [] for i in range(len(commands))}
        self.outgoing = {i: [] for i in range(len(commands))}
        for c in commands:
            i, op, a = c['index'], c['opcode'], c['args']
            if 'decode_error' in a:
                self.errors.append(f"#{i}: {a['decode_error']}")
                continue
            edges = []
            if op == 0x2BE: edges.append(Edge(i, a['target'], 'jump'))
            elif op == 0x2BF: edges.append(Edge(i, 0, 'file / end', a['script']))
            elif op in {0x65, 0x3F2}:
                edges.extend(Edge(i, v['target'], f"choice {j}: {v['label']}") for j, v in enumerate(a.get('choices', [])))
            elif op == 0x3F6:
                edges.extend(Edge(i, v['target'], f"{p}/{j}: {v['label']}")
                             for p, row in enumerate(a.get('parents', [])) for j, v in enumerate(row['children']))
            elif op == 0x3F8:
                edges.extend(Edge(i, v['target'], f'outcome {j}') for j, v in enumerate(a.get('outcomes', [])))
            elif op == 0x3FA:
                edges.extend(Edge(i, a[k], k) for k in ['win', 'lose', 'draw'])
            elif op == 0x3ED:
                if flow is None:self.errors.append(f'#{i}: profile owns the outer loop; its data-dependent destination is not indexed yet')
            else:
                if i + 1 < len(commands): edges.append(Edge(i, i + 1, 'fallthrough'))
                if op == 1:
                    edges.extend(Edge(i, a[k], k + ' boundary') for k in ['start', 'alternate', 'resume'] if a.get(k, -1) >= 0)
            for edge in edges:
                self.edges.append(edge)
                self.outgoing[i].append(edge)
                if edge.script is None:
                    if edge.target in self.incoming: self.incoming[edge.target].append(edge)
                    else: self.errors.append(f'#{i}: {edge.label} points outside script ({edge.target})')
        self.references = self.edges[:]
        self.entry_possible = set(range(len(commands)))
        if flow is not None:
            self.edges = [Edge(e['source'], e['target'], e['label'], None if e['script']==-2 else e['script']) for e in flow['edges']]
            self.incoming = {i: [] for i in range(len(commands))}
            self.outgoing = {i: [] for i in range(len(commands))}
            for edge in self.edges:
                self.outgoing[edge.source].append(edge)
                if edge.script is None and edge.target in self.incoming:self.incoming[edge.target].append(edge)
            self.errors += [f"#{e['command']}: {e['message']}" for e in flow.get('issues', [])]
            self.entry_possible = set(flow.get('entry_possible', []))


TEXT_OPS = {0x64, 0x65, 0x3F2, 0x3F6, 0x3F8, 0x3F9, 0x3EC}


def text_fields(command):
    """Only modifiable scenario text; exclude expressions and choice extras."""
    op, a = command['opcode'], command['args']
    if op == 0x64: return [('text', a.get('text', ''))]
    if op in {0x65, 0x3F2}:return [(f'choices[{i}].label', c['label']) for i,c in enumerate(a.get('choices', []))]
    if op == 0x3F6:
        out=[]
        for i,parent in enumerate(a.get('parents', [])):
            out.append((f'parents[{i}].label',parent['label']))
            out.extend((f'parents[{i}].children[{j}].label',c['label']) for j,c in enumerate(parent['children']))
        return out
    if op == 0x3F8:return [(f'outcomes[{i}].text', c['text']) for i,c in enumerate(a.get('outcomes', []))]
    if op in {0x3EC, 0x3F9}:return [(f'texts[{i}]', t) for i,t in enumerate(a.get('texts', []))]
    return []


def branch_options(command):
    op, a = command['opcode'], command['args']
    if op in {0x65, 0x3F2}:
        return [(v['label'].replace('\x00', ''), i, 0) for i, v in enumerate(a['choices'])]
    if op == 0x3F6:
        return [(f"{row['label']} → {v['label']}".replace('\x00', ''), p, j)
                for p, row in enumerate(a['parents']) for j, v in enumerate(row['children'])]
    if op == 0x3F8:
        return [(f"{'Success' if i == 0 else 'Failure'} → {v['text']}", i, 0)
                for i, v in enumerate(a['outcomes'])]
    if op == 0x3FA:
        return [(f'{label} → #{a[key]}', i, 0)
                for i, (label, key) in enumerate([('Win', 'win'), ('Lose', 'lose'), ('Draw', 'draw')])]
    return []


def prepare_condition(session, truth):
    """Bounded candidate search; the Python runtime evaluates every candidate.

    This supplies explicit sandbox variables, never changes a script expression.
    An unsolved/constant condition is reported without modifying the session.
    """
    expression = session.call('view')['args']['condition']
    variables = sorted(set(re.findall(r'\?([LG])(\d+)', expression)))
    if session.call('evaluate')['value'] == truth:
        return session.call('view')
    constants = {int(v) for v in re.findall(r'(?<![\w?])[-+]?\d+', re.sub(r'\?[LG]\d+', '', expression))}
    candidates = sorted({0, 1, -1, *(v + d for v in constants for d in (-1, 0, 1))})
    candidates = [v for v in candidates if -32768 <= v <= 32767]
    for values in itertools.islice(itertools.product(candidates, repeat=len(variables)), 12000):
        edits = [dict(kind=bank, index=int(index), value=value)
                 for (bank, index), value in zip(variables, values)]
        if session.call('evaluate', edits=edits)['value'] == truth:
            return session.call('patch', edits=edits)
    raise RuntimeError('No satisfying state found in the bounded search. Set variables manually; the expression has not been changed.')
