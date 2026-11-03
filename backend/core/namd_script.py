"""Validation and edits for the literal NAMD scripts qualified by NADOC.

NAMD initializes on run/minimize. Moving a static directive after that point can
fail only after a long calculation has finished. General Tcl needs separate
qualification; these helpers never execute it or reorder arbitrary commands.
"""
import re
import shlex


def validate_static_order(text):
    initialized = False
    for number, line in enumerate(text.splitlines(), 1):
        parts = shlex.split(line, comments=True)
        if not parts:
            continue
        key = parts[0].lower()
        if key in ('run', 'minimize'):
            if len(parts) != 2 or not re.fullmatch(r'\d+', parts[1]):
                raise ValueError(f'Line {number}: only literal {key} <steps> is qualified; '
                                 'run norepeat/upto and dynamic run expressions require separate validation')
            initialized = True
        elif initialized:
            raise ValueError(f'Line {number}: {key} follows run/minimize; '
                             'initialization settings must precede the first execution command')


def rewrite_probe(text, settings, *, steps=None):
    """Replace static settings before execution and optionally one literal run.

    Accept an archived malformed probe only when the caller explicitly replaces
    all misplaced settings. Preserve other commands and scientific input paths.
    """
    updates = {str(k).lower(): str(v) for k, v in settings.items()}
    if any(not re.fullmatch(r'[a-z][a-z0-9]*', k) or k in ('run','minimize','source','set')
           or any(c in v for c in '\n\r;[]') for k,v in updates.items()):
        raise ValueError('Probe settings must be literal initialization directives')
    if steps is not None and (type(steps) is not int or steps < 0):
        raise ValueError('Probe run steps must be a nonnegative integer')
    lines = []; runs = 0
    for line in text.splitlines():
        parts = shlex.split(line, comments=True)
        key = parts[0].lower() if parts else ''
        if key in updates:
            continue
        if key == 'run' and steps is not None:
            if len(parts)!=2 or not re.fullmatch(r'\d+',parts[1]):
                raise ValueError('Cannot rewrite an unqualified run command')
            line = f'run {steps}'; runs += 1
        lines.append(line)
    if steps is not None and runs != 1:
        raise ValueError('Probe requires exactly one literal run command')
    first = next((i for i,l in enumerate(lines) if re.match(r'^\s*(run|minimize)\b',l,re.I)),len(lines))
    lines[first:first] = [f'{k} {v}' for k,v in updates.items()]
    result = '\n'.join(lines)+'\n'
    validate_static_order(result)
    return result


def log_completed(path):
    """Require normal termination; checkpoint output alone never proves success."""
    ended = False
    try:
        with open(path, errors='replace') as stream:
            for line in stream:
                if ('FATAL ERROR' in line or re.match(r'^\s*ERROR:',line)
                        or 'Traceback (most recent call last)' in line):
                    return False
                if 'End of program' in line:
                    ended = True
    except OSError:
        return False
    return ended
