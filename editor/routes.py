"""Observed execution tapes, never one guessed state for a static block."""
from dataclasses import dataclass
import hashlib
import json


@dataclass
class Tape:
    number: int
    entry: int
    actions: list
    visits: list
    digests: list
    revision: str = 'original'


class RouteBook:
    def __init__(self):
        self.tapes = []

    def capture(self, session):
        route = session.call('route')
        digests = [hashlib.sha256(str(route['entry']).encode()).digest()]
        for action in route['actions']:
            encoded=json.dumps(action, sort_keys=True, ensure_ascii=False).encode()
            digests.append(hashlib.sha256(digests[-1]+encoded).digest())
        for tape in self.tapes:
            if tape.revision==route.get('revision','original') and tape.entry==route['entry'] and len(tape.actions)>=len(route['actions']) and tape.digests[len(route['actions'])]==digests[-1]:return tape
        tape=Tape(len(self.tapes)+1,route['entry'],route['actions'],route['visits'],digests,route.get('revision','original'))
        self.tapes.append(tape)
        return tape

    def find(self, script, command, phase='before', include_debug=False):
        matches=[]; seen=set()
        for tape in reversed(self.tapes):
            for visit in tape.visits:
                if (visit['script'],visit['command'],visit['phase'])!=(script,command,phase):continue
                if visit['sandbox'] and not include_debug:continue
                identity=tape.digests[visit['count']],phase
                if identity in seen:continue
                seen.add(identity);matches.append((tape,visit))
        return matches

    @staticmethod
    def restore(session, tape, count, expected=None):
        args=dict(entry=tape.entry,actions=tape.actions,count=count,revision=tape.revision)
        if expected:args['expected']=expected
        return session.call('restore',**args)
