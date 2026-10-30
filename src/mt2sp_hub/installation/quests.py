"""Pure preflight and read-only artifact ownership checks for quest staging.

These helpers do not run a compiler, deploy files or establish game support.
The caller must supply authoritative baseline inventories and an isolated,
finished compiler output directory for each quest.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

from ..core.validation import (MAX_FILE, MAX_FILES, MAX_PACKAGES, MAX_TOTAL,
                               confined, digest, logical_path, path_set, read_bounded)
from ..core.versions import satisfies
from ..errors import HubError, require

NAME = r'[A-Za-z_][A-Za-z0-9_]{0,63}'
WORD = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
LONG_STRING = re.compile(r'\[(=*)\[')


@dataclass(frozen=True)
class QuestSource:
    package_id: str
    name: str
    source: bytes

    @property
    def sha256(self):
        return digest(self.source)


def _name(value):
    require(isinstance(value, str) and re.fullmatch(NAME, value),
            'quest_name', 'Quest names must be ASCII identifiers of at most 64 characters.')
    logical_path(value)
    return value


def _tokens(text):
    """Recognize names without mistaking Lua strings/comments for declarations.

    This is deliberately not a quest parser; compiler success and artifact
    ownership validation remain separate required steps.
    """
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        comment = text.startswith('--', index)
        start = index + 2 if comment else index
        long = LONG_STRING.match(text, start)
        if long:
            end_marker = ']' + long[1] + ']'
            end = text.find(end_marker, long.end())
            require(end >= 0, 'quest_source', 'Unterminated long string or comment in quest source.')
            index = end + len(end_marker)
            if not comment:
                yield '@string'
            continue
        if comment:
            end = text.find('\n', start)
            index = len(text) if end < 0 else end + 1
            continue
        if text[index] in ('"', "'"):
            quote = text[index]
            index += 1
            while index < len(text) and text[index] != quote:
                require(text[index] != '\n', 'quest_source', 'Unterminated quoted string in quest source.')
                index += 2 if text[index] == '\\' else 1
            require(index < len(text), 'quest_source', 'Unterminated quoted string in quest source.')
            index += 1
            yield '@string'
            continue
        word = WORD.match(text, index)
        if word:
            yield word[0]
            index = word.end()
        else:
            yield text[index]
            index += 1


def _source_name(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_FILE,
            'quest_source', 'Quest source is missing or exceeds the package file limit.')
    normalized = raw.replace(b'\r\n', b'\n')
    require(all(value in (9, 10) or 32 <= value <= 126 for value in normalized),
            'quest_encoding', 'This initial quest profile accepts ASCII text and LF/CRLF line endings only.')
    prefix, declarations = [], 0
    for token in _tokens(normalized.decode('ascii')):
        if len(prefix) < 3:
            prefix.append(token)
        if token == 'quest':
            declarations += 1
    require(declarations == 1 and len(prefix) == 3 and prefix[0] == 'quest' and prefix[2] == 'begin',
            'quest_declaration', 'Use one quest declaration at the start of each source file.')
    return _name(prefix[1]), normalized


def collect_quests(packages, *, official_names):
    """Collect namespaced server sources; reject official/selected collisions.

    Package dependencies and client capabilities are the coordinator's job.
    official_names must describe the entire verified baseline, not a best guess.
    """
    require(isinstance(official_names, (set, frozenset)), 'quest_inventory', 'Provide the verified official quest-name inventory.')
    occupied = {_name(name).casefold() for name in official_names}
    require(len(occupied) == len(official_names), 'quest_inventory', 'Official quest names collide by case.')
    quests, package_ids, total = {}, set(), 0
    for package in packages:
        require(len(package_ids) < MAX_PACKAGES, 'package_limit', 'Too many selected packages.')
        manifest, files = package.unpack()
        ident = manifest['id']
        require(ident not in package_ids, 'duplicate_package', 'Duplicate selected package ID.')
        package_ids.add(ident)
        component = manifest['components'].get('server')
        if component is None:
            continue
        require(component['capabilities'] == ['server.quest'], 'quest_capability', 'Quest staging requires only the server.quest capability.')
        require(satisfies('1.0.0', component['api']), 'api_incompatible', 'This quest staging API does not satisfy the package requirement.')
        prefix = ident + '/quests/'
        quest_prefix = ident.replace('.', '_').replace('-', '_') + '_'
        for row in component['files']:
            target = row['target']
            require(target.startswith(prefix) and target.endswith('.quest') and '/' not in target[len(prefix):],
                    'quest_target', 'Put each server quest directly under PACKAGE_ID/quests/NAME.quest.')
            raw = files['server/' + target]
            name, source = _source_name(raw)
            require(target[len(prefix):-6] == name and name.startswith(quest_prefix),
                    'quest_identity', 'Quest name must match its filename and begin with the package prefix.')
            require(name.casefold() not in occupied, 'quest_conflict', 'A quest name is already owned by the baseline or another selected add-on.')
            occupied.add(name.casefold())
            total += len(raw)
            require(len(quests) < MAX_FILES and total <= MAX_TOTAL, 'selection_limit', 'Quest sources exceed the selection limits.')
            quests[name] = QuestSource(ident, name, source)
    return quests


def _artifact_path(name, relative):
    parts = relative.split('/')
    if parts == ['state', name]:
        return 'state'
    require(len(parts) == 3 and parts[0] != 'state'
            and all(re.fullmatch(r'[A-Za-z0-9_]{1,64}', part) for part in parts[:2]),
            'quest_artifact', 'Unexpected quest artifact layout.')
    require(re.fullmatch(re.escape(name) + r'\.' + NAME + r'(?:\.[0-9]+\.(?:script|when|arg))?', parts[2]),
            'quest_artifact', 'Compiler emitted an artifact outside the declared quest identity.')
    return 'handler'


def validate_artifacts(quest, files, *, occupied_paths):
    """Validate captured compiler bytes from a directory or bounded transport."""
    _name(quest.name)
    require(isinstance(occupied_paths, (set, frozenset)), 'quest_inventory', 'Provide the verified occupied artifact paths.')
    require(isinstance(files, dict) and len(files) <= MAX_FILES,
            'quest_artifact_limit', 'Too many compiler artifacts.')
    path_set([*occupied_paths, *files])
    groups, total = {}, 0
    for path, raw in files.items():
        require(path.startswith('object/'), 'quest_artifact', 'Unexpected quest artifact root.')
        relative = path[len('object/'):]
        _artifact_path(quest.name, relative)
        require(isinstance(raw, bytes) and len(raw) <= MAX_FILE,
                'quest_artifact_limit', 'Compiler artifacts must be bounded bytes.')
        total += len(raw)
        require(total <= MAX_TOTAL, 'quest_artifact_limit', 'Compiler output exceeds the package limits.')
        require(raw or re.search(r'\.[0-9]+\.when\Z', relative),
                'quest_artifact', 'A required compiler artifact is empty.')
        if re.search(r'\.[0-9]+\.(?:arg|when|script)\Z', relative):
            group, suffix = relative.rsplit('.', 1)
            groups.setdefault(group, set()).add(suffix)
    require('object/state/' + quest.name in files and len(files) > 1,
            'quest_artifact', 'Compiler must emit the declared state and at least one handler.')
    require(all(suffixes == {'arg', 'when', 'script'} for suffixes in groups.values()),
            'quest_artifact', 'A dialog artifact group is incomplete.')
    return dict(sorted(files.items()))


def read_artifacts(quest, output_directory, *, occupied_paths):
    """Read one compiler's object/ directory without following links or writing.

    Returns owned object-relative deployment paths and captured bytes. The caller
    must reject compiler failure before this call, then retain these exact bytes.
    occupied_paths includes official files and already staged add-on artifacts.
    """
    _name(quest.name)
    require(isinstance(occupied_paths, (set, frozenset)), 'quest_inventory', 'Provide the verified occupied artifact paths.')
    path_set(occupied_paths)
    root = Path(output_directory).absolute()
    files, directories, stack, total, count = {}, [], [('', root)], 0, 0
    try:
        confined(root, 'state')  # Also checks the output root itself for links.
        require(root.is_dir(), 'quest_artifact', 'Compiler output directory is missing.')
        while stack:
            parent, directory = stack.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    require(count <= MAX_FILES * 3, 'quest_artifact_limit', 'Too many compiler output entries.')
                    relative = parent + entry.name
                    path = confined(root, relative)
                    info = path.stat()
                    if stat.S_ISDIR(info.st_mode):
                        parts = relative.split('/')
                        require(len(parts) <= 2 and all(re.fullmatch(r'[A-Za-z0-9_]{1,64}', part) for part in parts)
                                and (parts[0] != 'state' or len(parts) == 1),
                                'quest_artifact', 'Unexpected compiler output directory.')
                        directories.append(relative + '/')
                        stack.append((relative + '/', path))
                        continue
                    _artifact_path(quest.name, relative)
                    require(stat.S_ISREG(info.st_mode), 'quest_artifact', 'Compiler artifacts must be regular files.')
                    require(len(files) < MAX_FILES and info.st_size <= MAX_FILE and total + info.st_size <= MAX_TOTAL,
                            'quest_artifact_limit', 'Compiler output exceeds the package limits.')
                    raw = read_bounded(path, MAX_FILE)
                    after = path.stat()
                    require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                            and len(raw) == info.st_size,
                            'quest_artifact_changed', 'Compiler output changed during inspection; compile again in isolated staging.')
                    files['object/' + relative] = raw
                    total += len(raw)
        require(all(any(path.startswith('object/' + directory) for path in files) for directory in directories),
                'quest_artifact', 'Compiler emitted an unused directory.')
        return validate_artifacts(quest, files, occupied_paths=occupied_paths)
    except OSError as exc:
        raise HubError('quest_artifact_io', 'Could not read compiler output; preserve the baseline and discard this staging result.') from exc
