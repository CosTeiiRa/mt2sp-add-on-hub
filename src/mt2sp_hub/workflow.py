"""Shared review workflow over the same commands and guards as the CLI."""
from dataclasses import dataclass
from pathlib import Path

from .cli import parser, run
from .errors import HubError, require


def command(*args):
    return run(parser().parse_args([str(arg) for arg in args]))


def failure(exc):
    if isinstance(exc, HubError):
        return 'Could not continue [{}]: {}'.format(exc.code, exc)
    return ('Could not complete this operation. Check folder access and free disk space, '
            'then check the installation again. Keep its Hub records and backups.')


def plan_text(plan):
    def label(row):
        return 'not installed' if row is None else '{} ({})'.format(
            row['version'], 'enabled' if row['enabled'] else 'disabled')
    lines = ['Review these changes before applying them:', '']
    for change in plan['selection_changes']:
        lines.append('{}: {} -> {}'.format(change['id'], label(change['before']), label(change['after'])))
    if not plan['selection_changes']:
        lines.append('No package selection changes.')
    lines.extend(['', 'Server restart: ' + ('required' if plan.get('server_restart') else 'not required'),
                  'Player progress and rewards are kept.',
                  'Close the selected game client and keep its updater and other managers idle.'])
    return '\n'.join(lines)


@dataclass(frozen=True)
class Review:
    root: Path
    action: str
    text: str
    token: str | None = None


class Workflow:
    """One selected target and at most one explicit review; no second installer."""
    def __init__(self, invoke=command):
        self.invoke = invoke
        self.root = None
        self.status = None
        self.setup_ready = False
        self.review = None

    def invalidate(self):
        self.status = None
        self.setup_ready = False
        self.review = None

    def select(self, root):
        self.invalidate()
        self.root = None
        self.root = Path(root).resolve()
        return self.refresh()

    def refresh(self):
        require(self.root is not None, 'choose_folder', 'Choose a game folder first.')
        self.invalidate()
        try:
            self.status = self.invoke('status', '--root', self.root)
        except HubError as exc:
            if exc.code != 'game_not_attached':
                raise
            report = self.invoke('probe', self.root, '--build', '--runtime')
            require(report['ownership']['status'] == 'no_hub_records', 'attachment_conflict',
                    'Existing ownership records need recovery or review. Keep them intact.')
            require(report['layout_complete'] and report['build']['status'] == 'reference_match',
                    'game_build', 'This folder does not match the reviewed official build. Setup is unavailable.')
            runtime = report['runtime']
            require(runtime.get('folder_binding') == 'matched' and runtime.get('server') == 'running'
                    and runtime.get('health') == 'healthy', 'server_not_ready',
                    'Start this game server through its normal launcher and wait for readiness, then check again.')
            self.setup_ready = True
            return 'Folder checks passed. Review setup to connect this game to Hub.'
        if self.status['recovery_required']:
            return 'An unfinished operation needs recovery before add-ons can be changed.'
        if self.status['kind'] == 'synthetic':
            return 'Practice sandbox checked. Changes here affect synthetic test files only.'
        return 'Installation checked. Choose a ZIP or select an installed add-on.'

    def prepare(self, action, value=None):
        self.review = None
        require(self.root is not None, 'choose_folder', 'Choose a game folder first.')
        if action == 'attach':
            require(self.setup_ready, 'setup_checks', 'Check this folder before setting up Hub.')
            text = ('Set up Hub for the selected game.\n\n'
                    'Hub will check this game, keep recovery data, and update its server '
                    'configuration so add-ons can be managed. Setup installs no add-ons.\n\n'
                    'Use a disposable test world for this preview. Close its client and keep '
                    'the launcher, updater and other managers idle during setup.')
            self.review = Review(self.root, action, text)
        elif action == 'recover':
            text = ('Recover the selected installation.\n\n'
                    'Hub will check its recovery records, then finish an interrupted setup, '
                    'restore the previous add-ons, or verify a change that already finished. '
                    'The selected game server may restart. Player progress and rewards are kept.\n\n'
                    'Close the client. Keep Docker and this world\'s database available. '
                    'Keep its server data and Hub backups; do not reset the world. '
                    'Keep other managers and the updater idle.')
            self.review = Review(self.root, action, text)
        else:
            require(action in ('add', 'remove', 'enable', 'disable'), 'interface_action', 'Unknown operation.')
            require(self.status and not self.status['recovery_required'], 'check_required',
                    'Check this installation and finish any recovery first.')
            plan = self.invoke('plan', '--root', self.root, '--' + action, value)
            self.review = Review(self.root, 'apply', plan_text(plan), plan['plan'])
        return self.review.text

    def confirm(self):
        review = self.review
        self.review = None  # Success or failure consumes the review. Never replay it silently.
        require(review is not None and review.root == self.root, 'review_required',
                'Review an operation for the selected folder before confirming it.')
        self.status = None
        self.setup_ready = False
        if review.action == 'attach':
            result = self.invoke('attach', self.root, '--yes')
        elif review.action == 'recover':
            result = self.invoke('recover', '--root', self.root, '--yes')
        else:
            result = self.invoke('apply', '--root', self.root, '--plan', review.token, '--yes')
        outcomes = {'applied': 'Changes applied.', 'rolled_back': 'Previous deployment restored.',
                    'nothing_pending': 'No interrupted operation needs recovery.'}
        message = 'Hub setup completed.' if result.get('attached') else outcomes.get(result.get('outcome'), 'Operation completed.')
        try:
            return message + '\n\n' + self.refresh()
        except Exception as exc:
            return message + '\n\nThe follow-up check did not finish.\n' + failure(exc)
