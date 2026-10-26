"""Check selected Python module boundaries and unresolved global names offline.

Uses only AST/symtable; it never imports application code or touches hardware.
This is a small regression guard, not control-flow/type analysis: dynamic imports,
global injection and local names read before assignment need other tests/review.
"""
from __future__ import annotations

import argparse
import ast
import builtins
from dataclasses import dataclass
from pathlib import Path
import symtable


ROOT=Path(__file__).resolve().parents[1]
MODULE_GLOBALS=set(dir(builtins))|{
    '__file__','__name__','__doc__','__package__','__spec__','__loader__',
    '__builtins__','__annotations__','__path__','__cached__',
}
PURE_FILES=('host/midi_source.py','host/pitch.py','host/arrangement_presets.py')
TRANSPORTS={'fastapi','starlette','ble_link','orchestra_link','floppy_link',
            'bleak','serial','socket','firmware'}
# Recovery hashes the compiled backbone for its diagnostic report. Preserve this
# known dependency explicitly; do not permit other runtime imports from playback.
IMPORT_EXCEPTIONS={
    ('host/playback/universal_recovery.py','runtime.compiler',('compile_plan',)),
}


@dataclass(frozen=True,order=True)
class Finding:
    path: str
    line: int
    code: str
    detail: str

    def __str__(self):
        return f'{self.path}:{self.line}: {self.code}: {self.detail}'


def _module_path(path):
    parts=list(Path(path).with_suffix('').parts)
    if parts and parts[0]=='host':parts.pop(0)
    if parts and parts[-1]=='__init__':parts.pop()
    return parts


def _imports(tree,path):
    parts=_module_path(path)
    package=parts if Path(path).stem=='__init__' else parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):
            for alias in node.names:
                module=alias.name.removeprefix('host.')
                yield node,module,()
        elif isinstance(node,ast.ImportFrom):
            if node.level:
                prefix=package[:len(package)-node.level+1]
                module='.'.join(prefix+([node.module] if node.module else []))
            else:
                module=(node.module or '').removeprefix('host.')
            names=tuple(alias.name for alias in node.names)
            yield node,module,names
            # ``from . import virtual`` names a submodule in its aliases.
            if node.module is None:
                for name in names:
                    if name!='*':yield node,module+'.'+name,(name,)


def _boundary(path,module):
    family=module.split('.')[0]
    if path.startswith('host/playback/'):
        if family in {'runtime','web'}|TRANSPORTS:
            return 'planning must not import application controllers or live transports'
        if path=='host/playback/device_models.py' and module=='playback.virtual':
            return 'shared device models must not depend on the preview implementation'
    if path.startswith('host/runtime/') and family in {'web','fastapi','starlette'}:
        return 'application operations must not depend on HTTP/WebSocket controllers'
    if path in {'host/web/library.py','host/web/contracts.py'}:
        if family in {'runtime'}|TRANSPORTS or module=='web.server':
            return 'library/validation modules must remain independent of runtime and HTTP'
    if path in PURE_FILES and family in {'runtime','web','playback'}|TRANSPORTS:
        return 'source parsing, pitch and preset data must remain independent of runtime'
    return None


def check_source(source,path):
    """Return findings for one source string, using its repository-relative path."""
    path=Path(path).as_posix()
    try:
        tree=ast.parse(source,filename=path)
        table=symtable.symtable(source,path,'exec')
    except SyntaxError as exc:
        return [Finding(path,exc.lineno or 1,'syntax',exc.msg)]
    findings=[]
    defined=MODULE_GLOBALS|{symbol.get_name() for symbol in table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()}
    def visit(scope):
        for symbol in scope.get_symbols():
            if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in defined:
                findings.append(Finding(path,max(1,scope.get_lineno()),'undefined-global',
                    f'{symbol.get_name()} in {scope.get_name()}'))
        for child in scope.get_children():visit(child)
    visit(table)
    seen=set()
    for node,module,names in _imports(tree,path):
        if '*' in names:
            findings.append(Finding(path,node.lineno,'wildcard-import',
                                    'explicit imported names are required for this check'))
        problem=_boundary(path,module)
        if problem and (path,module,names) not in IMPORT_EXCEPTIONS:
            key=node.lineno,module
            if key not in seen:
                findings.append(Finding(path,node.lineno,'import-boundary',f'{module}: {problem}'))
                seen.add(key)
    return sorted(set(findings))


def source_paths(root):
    """Cover active runtime/web/planning modules plus their pure entry contracts."""
    paths=set()
    for directory in ('host/runtime','host/web','host/playback'):
        paths.update((root/directory).rglob('*.py'))
    paths.update(root/path for path in PURE_FILES if (root/path).is_file())
    return sorted(paths)


def check(root):
    paths=source_paths(root)
    findings=[]
    for path in paths:
        findings.extend(check_source(path.read_text(encoding='utf-8'),path.relative_to(root)))
    return findings,len(paths)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args(argv)
    findings,count=check(args.root)
    for finding in findings:print(finding)
    if findings:
        print(f'Architecture check failed: {len(findings)} finding(s) in {count} modules')
        return 1
    if not count:
        print('Architecture check failed: no covered Python modules found')
        return 1
    print(f'Architecture check passed: {count} Python modules; no undefined globals or boundary violations')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
