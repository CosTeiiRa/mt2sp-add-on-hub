"""Small local desktop workflow over the same commands and guards as the CLI."""
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

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
            require(action in ('add', 'remove', 'enable', 'disable'), 'desktop_action', 'Unknown operation.')
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


class Worker:
    """Only one operation at a time; Tk is touched only by the main thread."""
    def __init__(self):
        self.busy = False
        self.results = Queue()

    def start(self, operation):
        require(not self.busy, 'desktop_busy', 'Wait for the current operation to finish.')
        self.busy = True

        def work():
            try:
                result = (operation(), False)
            except Exception as exc:
                result = (failure(exc), True)
            self.results.put(result)

        try:
            Thread(target=work, daemon=False).start()
        except Exception:
            self.busy = False
            raise

    def poll(self):
        try:
            result = self.results.get_nowait()
        except Empty:
            return None
        self.busy = False
        return result


class Desktop:
    def __init__(self, window, root=None):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        from tkinter.scrolledtext import ScrolledText
        self.window, self.dialog, self.messages = window, filedialog, messagebox
        self.workflow, self.worker = Workflow(), Worker()
        self.folder = tk.StringVar(value='Choose your Metin2 Singleplayer folder to begin.')
        self.note = tk.StringVar(value='Experimental preview - use a disposable test installation.')
        window.title('MT2SP Add-on Hub')
        window.geometry('900x720')
        window.minsize(740, 620)
        window.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        frame.rowconfigure(7, weight=2)
        ttk.Label(frame, text='Add-on Hub', font=('Segoe UI', 20, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(frame, textvariable=self.note, wraplength=810).grid(row=1, column=0, sticky='w', pady=(4, 14))
        ttk.Label(frame, textvariable=self.folder, wraplength=810).grid(row=2, column=0, sticky='w')
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=3, column=0, sticky='ew', pady=10)
        self.controls = {}

        def button(parent, key, label, callback):
            widget = ttk.Button(parent, text=label, command=callback)
            widget.pack(side='left', padx=(0, 8), pady=2)
            self.controls[key] = widget

        button(toolbar, 'choose', 'Choose folder...', self.choose)
        button(toolbar, 'check', 'Check again', lambda: self.start(self.workflow.refresh, 'Checking installation...'))
        button(toolbar, 'setup', 'Review setup', lambda: self.prepare('attach'))
        button(toolbar, 'recover', 'Review recovery', lambda: self.prepare('recover'))
        table_frame = ttk.Frame(frame)
        table_frame.grid(row=4, column=0, sticky='nsew')
        self.table = ttk.Treeview(table_frame, columns=('id', 'version', 'state'), show='headings', height=6, selectmode='browse')
        for column, label, width in [('id', 'Installed add-on', 400), ('version', 'Version', 140), ('state', 'State', 120)]:
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=80)
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda event: self.controls_state())
        actions = ttk.Frame(frame)
        actions.grid(row=5, column=0, sticky='ew', pady=10)
        button(actions, 'add', 'Import ZIP...', self.import_zip)
        button(actions, 'enable', 'Enable', lambda: self.selected_action('enable'))
        button(actions, 'disable', 'Disable', lambda: self.selected_action('disable'))
        button(actions, 'remove', 'Remove', lambda: self.selected_action('remove'))
        ttk.Label(frame, text='Review and result', font=('Segoe UI', 10, 'bold')).grid(row=6, column=0, sticky='w')
        self.details = ScrolledText(frame, height=10, wrap='word', font=('Segoe UI', 10), state='disabled')
        self.details.grid(row=7, column=0, sticky='nsew', pady=(6, 10))
        confirmation = ttk.Frame(frame)
        confirmation.grid(row=8, column=0, sticky='ew')
        button(confirmation, 'confirm', 'Confirm reviewed operation', lambda: self.start(self.workflow.confirm, 'Applying reviewed operation...'))
        button(confirmation, 'cancel', 'Cancel review', self.cancel)
        self.progress = ttk.Progressbar(confirmation, mode='indeterminate', length=150)
        self.show('Choose a folder, import an add-on ZIP, review its changes, then confirm.\n\n'
                  'Imported add-ons run code inside the game. Use packages from creators you trust.\n'
                  'The Hub can be closed after installation.')
        self.controls_state()
        window.report_callback_exception = self.callback_error
        window.after(100, self.poll)
        if root is not None:
            self.select(root)

    def show(self, text):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def controls_state(self):
        flow = self.workflow
        selected = self.table.selection()
        ready = bool(flow.status and not flow.status['recovery_required'])
        enabled = bool(selected and self.table.item(selected[0], 'values')[2] == 'Enabled')
        active = not self.worker.busy
        normal = active and flow.review is None
        states = {'choose': active, 'check': normal and flow.root is not None,
                  'setup': normal and flow.setup_ready, 'recover': normal and flow.root is not None,
                  'add': normal and ready, 'enable': normal and ready and bool(selected) and not enabled,
                  'disable': normal and ready and bool(selected) and enabled,
                  'remove': normal and ready and bool(selected),
                  'confirm': active and flow.review is not None, 'cancel': active and flow.review is not None}
        for key, widget in self.controls.items():
            widget.configure(state='normal' if states[key] else 'disabled')

    def start(self, operation, message):
        if self.worker.busy:
            return
        self.note.set(message + ' This can take a few minutes; keep this window open.')
        self.show(message)
        self.worker.start(operation)
        self.progress.pack(side='right', fill='x', expand=True)
        self.progress.start(15)
        self.controls_state()

    def poll(self):
        result = self.worker.poll()
        if result is not None:
            text, failed = result
            if failed:
                self.workflow.invalidate()
            self.progress.stop()
            self.progress.pack_forget()
            unchecked = (self.workflow.root is not None and self.workflow.status is None
                         and not self.workflow.setup_ready and self.workflow.review is None)
            self.note.set('Check needed - see the result below.' if failed or unchecked else
                          'Review ready - confirm to make changes.' if self.workflow.review else
                          'Recovery needed - review it before changing add-ons.' if (self.workflow.status or {}).get('recovery_required') else
                          'Practice sandbox - synthetic files only.' if (self.workflow.status or {}).get('kind') == 'synthetic' else
                          'Experimental preview - use a disposable test installation.')
            self.table.delete(*self.table.get_children())
            for row in (self.workflow.status or {}).get('packages', []):
                self.table.insert('', 'end', iid=row['id'], values=(row['id'], row['version'], 'Enabled' if row['enabled'] else 'Disabled'))
            self.show(text)
            self.controls_state()
        self.window.after(100, self.poll)

    def choose(self):
        root = self.dialog.askdirectory(parent=self.window, title='Choose the Metin2 Singleplayer folder')
        if root:
            self.select(root)

    def select(self, root):
        if self.worker.busy:
            return
        self.folder.set(str(Path(root).resolve()))
        self.start(lambda: self.workflow.select(root), 'Checking selected folder...')

    def import_zip(self):
        path = self.dialog.askopenfilename(parent=self.window, title='Choose an add-on ZIP', filetypes=[('Add-on ZIP', '*.zip')])
        if path:
            self.prepare('add', path)

    def selected_action(self, action):
        selected = self.table.selection()
        if selected:
            self.prepare(action, selected[0])

    def prepare(self, action, value=None):
        self.start(lambda: self.workflow.prepare(action, value), 'Preparing review...')

    def cancel(self):
        self.workflow.review = None
        self.note.set('Review cancelled. Choose another operation when ready.')
        self.show('Review discarded. Installed add-ons have not changed.')
        self.controls_state()

    def close(self):
        if self.worker.busy:
            self.messages.showinfo('Operation in progress', 'Wait for this operation to finish before closing Hub.', parent=self.window)
        else:
            self.window.destroy()

    def callback_error(self, *_):
        if not self.worker.busy:
            self.workflow.invalidate()
            self.controls_state()
        self.messages.showerror('Hub interface', 'The interface could not complete that action. Check the installation again before continuing.', parent=self.window)


def launch(root=None):
    try:
        import tkinter as tk
        window = tk.Tk()
    except (ImportError, RuntimeError):
        print('The desktop interface needs Python with Tcl/Tk support.')
        return 2
    except Exception:
        print('Could not open the desktop interface. A graphical desktop and Tcl/Tk are required.')
        return 2
    Desktop(window, root)
    window.mainloop()
    return 0


def main():
    import argparse
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument('--root', type=Path, help='Open a selected game or existing practice sandbox')
    return launch(options.parse_args().root)
