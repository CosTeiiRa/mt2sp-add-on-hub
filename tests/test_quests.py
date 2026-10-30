import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from helpers import archive
from mt2sp_hub.authoring import create
from mt2sp_hub.core.packages import build
from mt2sp_hub.core.validation import digest
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation import quests


NAME = 'example_hello_greeting'


class QuestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='hub-quest-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'package'
        create(self.source, 'example.hello', 'combined', profile='game')
        self.quest_file = self.source / ('payload/server/' + NAME + '.quest')
        self.output = self.root / 'compiled/object'
        self.output.mkdir(parents=True)

    def collect(self, raw=None, official_names=frozenset()):
        if raw is not None:
            self.quest_file.write_bytes(raw)
        return quests.collect_quests([build(self.source)], official_names=official_names)

    def write_outputs(self, extra=None):
        files = {'state/' + NAME: b'invented state artifact',
                 'notarget/login/' + NAME + '.start': b'invented login artifact'}
        files.update(extra or {})
        for relative, raw in files.items():
            path = self.output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return {'object/' + relative: raw for relative, raw in files.items()}

    def read(self, occupied_paths=frozenset()):
        return quests.read_artifacts(self.collect()[NAME], self.output, occupied_paths=occupied_paths)

    def assert_error(self, code, operation):
        with self.assertRaises(HubError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return str(caught.exception)

    def test_starter_is_collected_with_normalized_source_and_stable_digest(self):
        raw = self.quest_file.read_bytes().replace(b'\n', b'\r\n')
        quest = self.collect(raw, {'official_one'})[NAME]
        self.assertEqual(quest.package_id, 'example.hello')
        self.assertNotIn(b'\r', quest.source)
        self.assertEqual(quest.sha256, digest(raw.replace(b'\r\n', b'\n')))
        self.assertEqual(self.quest_file.read_bytes(), raw)

    def test_comments_strings_and_long_brackets_cannot_spoof_declarations(self):
        raw = (b'-- quest fake begin\n--[=[ quest hidden begin ]=]\n'
               b'quest ' + NAME.encode() + b' begin\n'
               b'state start begin when login begin\n'
               b'chat("quest quoted begin")\nchat(\'escaped\\\' quest quoted begin\')\n'
               b'chat([==[ quest long_string begin ]==])\nend end end\n')
        self.assertEqual(list(self.collect(raw)), [NAME])

    def test_multiple_or_misplaced_declarations_and_bad_strings_are_rejected(self):
        raw = self.quest_file.read_bytes()
        for value in (raw + b'quest second begin end\n', b'local x = 1\n' + raw,
                      b'"ignored prefix"\n' + raw, raw.replace(b'quest ', b'quest "literal" ', 1)):
            self.assert_error('quest_declaration', lambda: self.collect(value))
        for value in (raw + b'--[=[ unclosed', raw + b'chat("unclosed)', raw + b'chat([[unclosed)'):
            self.assert_error('quest_source', lambda: self.collect(value))

    def test_encoding_and_names_must_match_the_profile(self):
        raw = self.quest_file.read_bytes()
        for suffix in (b'\x00', b'\xff', b'\r'):
            self.assert_error('quest_encoding', lambda: self.collect(raw + suffix))
        self.assert_error('quest_identity', lambda: self.collect(raw.replace(NAME.encode(), b'wrong_name', 1)))
        self.assert_error('quest_conflict', lambda: self.collect(raw, {NAME.upper()}))
        self.assert_error('quest_inventory', lambda: self.collect(raw, {'Official', 'official'}))
        self.assert_error('quest_inventory', lambda: self.collect(raw, []))

    def test_package_namespacing_capabilities_and_api_are_checked(self):
        manifest, files = build(self.source).unpack()
        members = {'payload/' + row['source']: files[kind + '/' + row['target']]
                   for kind, component in manifest['components'].items() for row in component['files']}
        for value, code in (('other.namespace/quests/' + NAME + '.quest', 'quest_target'),
                            ('example.hello/quests/nested/' + NAME + '.quest', 'quest_target'),
                            ('example.hello/quests/wrong.quest', 'quest_identity')):
            changed = json.loads(json.dumps(manifest))
            changed['components']['server']['files'][0]['target'] = value
            self.assert_error(code, lambda: quests.collect_quests([archive(changed, members)], official_names=set()))
        changed = json.loads(json.dumps(manifest))
        changed['components']['server']['capabilities'] = ['fixture.files']
        self.assert_error('quest_capability', lambda: quests.collect_quests([archive(changed, members)], official_names=set()))
        changed['components']['server']['capabilities'] = ['server.quest']
        changed['components']['server']['api'] = '>=2.0.0'
        self.assert_error('api_incompatible', lambda: quests.collect_quests([archive(changed, members)], official_names=set()))

    def test_two_different_package_ids_cannot_claim_the_same_quest(self):
        packages = []
        for ident in ('example.a-b', 'example.a_b'):
            source = self.root / ident
            create(source, ident, 'server', profile='game')
            packages.append(build(source))
        self.assert_error('quest_conflict', lambda: quests.collect_quests(packages, official_names=set()))
        self.assert_error('duplicate_package', lambda: quests.collect_quests([packages[0], packages[0]], official_names=set()))

    def test_client_only_packages_have_no_quest_sources(self):
        source = self.root / 'client'
        create(source, 'example.client', 'client', profile='game')
        self.assertEqual(quests.collect_quests([build(source)], official_names=set()), {})

    def test_source_limits_count_original_bytes_before_newline_normalization(self):
        raw = self.quest_file.read_bytes().replace(b'\n', b'\r\n')
        self.quest_file.write_bytes(raw)
        with patch.object(quests, 'MAX_TOTAL', len(raw)):
            self.assertEqual(len(self.collect()), 1)
        with patch.object(quests, 'MAX_TOTAL', len(raw) - 1):
            self.assert_error('selection_limit', self.collect)
        with patch.object(quests, 'MAX_FILES', 0):
            self.assert_error('selection_limit', self.collect)
        with patch.object(quests, 'MAX_PACKAGES', 0):
            self.assert_error('package_limit', self.collect)

    def test_actual_supported_artifact_shapes_are_read_without_mutation(self):
        expected = self.write_outputs({
            '12345/chat/' + NAME + '.start.0.arg': b'invented dialog label',
            '12345/chat/' + NAME + '.start.0.when': b'',
            '12345/chat/' + NAME + '.start.0.script': b'invented dialog script',
            'example_timer/timer/' + NAME + '.start': b'invented timer script'})
        before = {p.relative_to(self.output).as_posix(): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        original = Path.open
        def readonly(path, mode='r', *args, **kwargs):
            self.assertFalse(any(flag in mode for flag in 'wax+'))
            return original(path, mode, *args, **kwargs)
        quest = self.collect()[NAME]
        with patch.object(Path, 'open', readonly):
            actual = quests.read_artifacts(quest, self.output, occupied_paths={'object/state/official_one'})
        self.assertEqual(actual, expected)
        self.assertEqual(list(actual), sorted(actual))
        after = {p.relative_to(self.output).as_posix(): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_unexpected_quest_names_and_output_files_are_rejected(self):
        self.write_outputs()
        for relative in ('state/foreign_quest', 'notarget/login/foreign_quest.start',
                         'notarget/login/' + NAME + '_other.start',
                         'notarget/login/' + NAME + '.start.extra', 'private.txt'):
            path = self.output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'invented unwanted output')
            self.assert_error('quest_artifact', self.read)
            path.unlink()

    def test_missing_empty_and_incomplete_outputs_are_rejected(self):
        self.assert_error('quest_artifact', self.read)
        self.write_outputs()
        state = self.output / 'state' / NAME
        state.unlink()
        self.assert_error('quest_artifact', self.read)
        state.write_bytes(b'')
        self.assert_error('quest_artifact', self.read)
        state.write_bytes(b'invented state')
        part = self.output / ('12345/chat/' + NAME + '.start.0.arg')
        part.parent.mkdir(parents=True)
        part.write_bytes(b'invented arg')
        self.assert_error('quest_artifact', self.read)

    def test_an_empty_handler_named_when_is_not_a_valid_empty_condition(self):
        self.write_outputs({'notarget/login/' + NAME + '.when': b''})
        self.assert_error('quest_artifact', self.read)

    def test_existing_artifacts_case_aliases_and_parent_files_are_never_overwritten(self):
        self.write_outputs()
        for occupied in ({'object/state/' + NAME}, {'OBJECT/STATE/' + NAME.upper()}, {'object/notarget'}):
            self.assert_error('path_collision', lambda: self.read(occupied))
        self.assertEqual((self.output / 'state' / NAME).read_bytes(), b'invented state artifact')

    def test_links_and_extra_directory_depth_are_rejected(self):
        self.write_outputs()
        extra = self.output / 'extra/one/two'
        extra.mkdir(parents=True)
        self.assert_error('quest_artifact', self.read)
        extra.rmdir()
        extra.parent.rmdir()
        extra.parent.parent.rmdir()
        target = self.output / ('notarget/login/' + NAME + '.start')
        target.unlink()
        outside = self.root / 'outside'
        outside.write_bytes(b'private-outside-sentinel')
        try:
            target.symlink_to(outside)
        except OSError:
            self.skipTest('Host does not permit creating symbolic links')
        self.assert_error('path_link', self.read)

    def test_file_total_and_count_boundaries(self):
        expected = self.write_outputs()
        largest = max(map(len, expected.values()))
        total = sum(map(len, expected.values()))
        with patch.object(quests, 'MAX_FILE', largest), patch.object(quests, 'MAX_TOTAL', total), patch.object(quests, 'MAX_FILES', 2):
            # Use an already collected source; these bounds apply to artifacts.
            quest = quests.QuestSource('example.hello', NAME, b'invented source')
            self.assertEqual(quests.read_artifacts(quest, self.output, occupied_paths=set()), expected)
            for setting, value in (('MAX_FILE', largest - 1), ('MAX_TOTAL', total - 1), ('MAX_FILES', 1)):
                with patch.object(quests, setting, value):
                    self.assert_error('quest_artifact_limit', lambda: quests.read_artifacts(quest, self.output, occupied_paths=set()))

    def test_changed_output_and_io_errors_do_not_expose_private_paths(self):
        self.write_outputs()
        original = quests.read_bounded
        def changed(path, limit):
            raw = original(path, limit)
            path.write_bytes(raw + b'changed')
            return raw
        quest = self.collect()[NAME]
        with patch.object(quests, 'read_bounded', changed):
            self.assert_error('quest_artifact_changed', lambda: quests.read_artifacts(quest, self.output, occupied_paths=set()))
        with patch.object(quests.os, 'scandir', side_effect=OSError('private-path-sentinel')):
            message = self.assert_error('quest_artifact_io', lambda: quests.read_artifacts(quest, self.output, occupied_paths=set()))
            self.assertNotIn('private-path-sentinel', message)
