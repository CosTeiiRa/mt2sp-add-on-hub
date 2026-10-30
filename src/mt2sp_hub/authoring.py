"""Original sandbox and experimental game source starters for package authors."""
import json
from pathlib import Path

from .core.packages import validate_manifest
from .core.validation import identifier
from .errors import HubError, require

CLIENT_MAIN = '''"""A greeting window, recreated for each gameplay session."""


def register(context):
    window = context.module('window')
    greeting = context.register_window('greeting', window.Greeting)
    context.on('game.open', lambda game: greeting.open())
'''

CLIENT_WINDOW = '''"""Original minimal UI example; requires the game's ui module."""
import ui


class Greeting(object):
    def __init__(self, game):
        self.board = ui.BoardWithTitleBar()
        self.board.SetSize(260, 100)
        self.board.SetPosition(30, 60)
        self.board.AddFlag('movable')
        self.board.SetTitleName('Hello add-on')
        self.label = ui.TextLine()
        self.label.SetParent(self.board)
        self.label.SetPosition(20, 45)
        self.label.SetText('Your first client add-on is running.')
        self.label.Show()
        self.board.SetCloseEvent(self.Close)

    def Open(self):
        self.board.Show()

    def Close(self):
        if self.board is not None:
            self.board.Hide()

    def IsShow(self):
        return self.board is not None and self.board.IsShow()

    def Destroy(self):
        self.Close()
        if self.board is not None:
            self.board.SetCloseEvent(None)
            self.label.Hide()
        self.label = None
        self.board = None
'''


def _game_sources(ident, kinds):
    result = {}
    if 'client' in kinds:
        result['client'] = {'main.py': CLIENT_MAIN, 'window.py': CLIENT_WINDOW}
    if 'server' in kinds:
        name = ident.replace('.', '_').replace('-', '_') + '_greeting'
        require(len(name) <= 64, 'quest_name', 'Use a shorter package ID for this quest starter (at most 55 characters).')
        result['server'] = {name + '.quest': (
            'quest ' + name + ' begin\n'
            '    state start begin\n'
            '        when login begin\n'
            '            chat("Hello from your first server add-on.")\n'
            '        end\n'
            '    end\n'
            'end\n')}
    return result


def create(directory: Path, ident: str, kind: str, *, profile='sandbox'):
    require(kind in ("client", "server", "combined"), "component",
            "Choose client, server or combined.")
    require(profile in ('sandbox', 'game'), 'profile', 'Choose sandbox or game.')
    identifier(ident)
    kinds = ("client", "server") if kind == "combined" else (kind,)
    game_sources = _game_sources(ident, kinds) if profile == 'game' else {}
    payload = {}
    manifest = {"format_version": 2, "id": ident, "version": "0.1.0",
                "name": "My " + profile + " add-on", "license": "MIT",
                "requires": {}, "conflicts": [], "components": {}}
    for component in kinds:
        manifest["components"][component] = {
            "api": ">=1.0.0 <2.0.0", "capabilities": ["fixture.files"],
            "files": [{"source": component + ".txt", "target": ident + "/message.txt"}]}
        if profile == 'game':
            rows = []
            for name, text in game_sources[component].items():
                source = component + '/' + name
                target = ident + '/' + ('quests/' if component == 'server' else '') + name
                rows.append({'source': source, 'target': target})
                payload[source] = text.encode('ascii')
            manifest['components'][component]['files'] = rows
            manifest['components'][component]['capabilities'] = [
                'client.module' if component == 'client' else 'server.quest']
        else:
            payload[component + '.txt'] = ('Original synthetic ' + component + ' content.\n').encode('ascii')
    validate_manifest(manifest, source=True)
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise HubError("project_exists", "Starter folder already exists. Choose a new folder.") from exc
    (directory / "payload").mkdir()
    for name, raw in payload.items():
        path = directory / 'payload' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (directory / "addon.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
