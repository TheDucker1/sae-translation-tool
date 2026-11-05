"""Python control-flow/variable semantics. Reference: commands.cpp and flow.cpp."""
import operator
import re
from collections import deque


def signed16(value): return (value + 32768) % 65536 - 32768


def numeric(expression, banks=None):
    if re.fullmatch(r'\?.[0-9]+', expression):
        bank = 'L' if expression[1] == 'L' else 'G'
        index = int(expression[2:])
        if not 0 <= index < (1024 if bank == 'L' else 80): raise ValueError('Variable index outside bank')
        return banks[bank][index] if banks is not None else 0
    if not re.fullmatch(r'-?[0-9]+', expression): raise ValueError('Invalid numeric expression')
    value = int(expression)
    if not -2147483648 <= value <= 2147483647: raise ValueError('Numeric expression exceeds signed32')
    return value


def condition(expression, banks=None):
    if ('&&' in expression and '||' in expression) or '(' in expression or ')' in expression:
        raise ValueError('Unverified mixed/parenthesized condition grammar')
    terms = expression.split('&&' if '&&' in expression else '||')
    results = []
    for term in terms:
        match = re.fullmatch(r'(.+?)(==|!=|<=|>=|<|>)(.+)', term)
        if not match: raise ValueError('Condition term requires a comparison')
        left, op, right = match.groups()
        results.append({'==':operator.eq,'!=':operator.ne,'<=':operator.le,'>=':operator.ge,
                        '<':operator.lt,'>':operator.gt}[op](numeric(left,banks),numeric(right,banks)))
    return all(results) if '&&' in expression else any(results)


def dispatch(pc, stack, count, target=-1):
    """Return cursor + independent stack, preserving native signed16 comparisons."""
    stack = list(stack)
    if target != -1:
        if not 0 <= target < count: raise ValueError('Dispatch destination outside command vector')
        t = signed16(target)
        stack = [n for n in stack if not ((signed16(n[1]) != -1 and t > signed16(n[1])) or
                 (signed16(n[0]) == -1 and t <= signed16(n[1])) or t <= n[0] or t >= n[2])]
        return target, tuple(stack)
    pc += 1
    if pc >= count: return count, tuple(stack)
    removed = True
    while removed:
        removed = False
        for i in range(len(stack)-1,-1,-1):
            start, alternate, resume = map(signed16,stack[i]); cursor = signed16(pc)
            erase = False
            if start == -1 and alternate == -1: pc = resume; erase = True
            elif start == -1:
                if cursor < alternate: pc = alternate
                elif cursor >= resume: erase = True
            elif (alternate == -1 and cursor >= resume) or (alternate != -1 and cursor >= alternate):
                pc = resume; erase = True
            if erase: del stack[i]; removed = True
    if not 0 <= pc < count: raise ValueError('Dispatch destination outside command vector')
    return pc, tuple(stack)


def flow_index(commands, budget=20000, profile_links=None):
    edges, issues, seen, reached, work = set(), [], set(), set(), deque()
    def drain():
        while work and len(seen) < budget:
            pc, stack = work.popleft()
            if not 0 <= pc < len(commands) or (pc,stack) in seen: continue
            seen.add((pc,stack)); reached.add(pc)
            c = commands[pc]; op, a = c['opcode'], c['args']
            try:
                if 'decode_error' in a: raise ValueError(a['decode_error'])
                if op == 0x3ed:
                    targets=(profile_links or {}).get(a['id'])
                    if targets is None:edges.add((pc,-1,-3,'unresolved profile handoff'))
                    else:
                        for file in targets:edges.add((pc,0,file,'profile handoff' if file>=0 else 'profile end'))
                    continue
                if op == 0x2bf:
                    file = max(-1,a['script']); edges.add((pc,0,file,'end' if file < 0 else 'file')); continue
                if op == 1:
                    alternatives = [(-1, ('true: ' if truth else 'false: ')+a['condition'],
                                      stack+((a['start'] if truth else -1,a['alternate'],a['resume']),)) for truth in (True,False)]
                elif op == 0x2be: alternatives = [(a['target'],'jump',stack)]
                elif op in {0x65,0x3f2}: alternatives = [(c['target'],c['label'],stack) for c in a['choices']]
                elif op == 0x3f6: alternatives = [(c['target'],p['label']+' / '+c['label'],stack) for p in a['parents'] for c in p['children']]
                elif op == 0x3f8: alternatives = [(c['target'],'success' if i==0 else 'failure',stack) for i,c in enumerate(a['outcomes'])]
                elif op == 0x3fa: alternatives = [(a[k],k,stack) for k in ('win','lose','draw')]
                else: alternatives = [(-1,'next',stack)]
                for target,label,nodes in alternatives:
                    nxt,nodes = dispatch(pc,nodes,len(commands),target)
                    if nxt == len(commands): edges.add((pc,0,-1,'end')); continue
                    if label == 'next' and nxt != pc+1: label = 'merge'
                    edges.add((pc,nxt,-2,label)); work.append((nxt,nodes))
            except (ValueError,KeyError,IndexError) as e: issues.append(dict(command=pc,message=str(e)))
    if commands: work.append((0,()))
    drain(); entry = sorted(reached)
    for pc in range(len(commands)):
        if len(seen) >= budget: break
        if pc not in reached: work.append((pc,())); drain()
    if work or len(seen)>=budget: issues.append(dict(command=-1,message='Static flow context budget reached; some edges remain unresolved'))
    return dict(edges=[dict(source=s,target=t,script=f,label=l) for s,t,f,l in sorted(edges)],
                issues=issues,entry_possible=entry,contexts=len(seen))
