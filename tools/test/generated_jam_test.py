#!/usr/bin/env python3
# Copyright (c) 2026 WebCpp.org
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE_1_0.txt or copy at
# https://www.boost.org/LICENSE_1_0.txt)

"""Checks webcpp.generated (tools/generated/generated.jam): generated-<name> runs a library's Python
generator in its Jamfile's directory into the build directory, and passes when every output equals
its committed file, byte for byte, and fails naming each one that differs, with the command that
writes it again, each one that is missing, and each one the generator did not write; it leaves the
tree as it was, passing or failing. update-generated writes the outputs of every generator of the
Jamfile in place, and leaves every committed file as it was when any generator fails. An own lane
names the check, which `b2 declared-lanes` lists and the ordinary lanes never build, nor
update-generated; none of them, the lane included, runs the Jamroot's check of Boost, so they build
without Boost, while a lane of programs still runs it; and a wrong declaration, two generators that
name one output among them, stops the build by name.

Each case builds a scratch superproject with the fixture library demo, whose path holds a space.
Run with the names of some cases to run only those."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import harness

LIBRARY = 'libs/gen'
CHECK = f'{LIBRARY}/test//generated-words'
UPDATE = f'{LIBRARY}/test//update-generated'
LANE = f'{LIBRARY}/test//words'

JAMFILE = ('import webcpp ;\n'
           '\n'
           'webcpp.generated words : gen.py : forty-two\n'
           '  : generated/words.txt generated/more/twice.txt ;\n'
           'webcpp.lane words : generated-words ;\n')

# The generator: from its Jamfile's directory, where it finds itself, it writes its word into the
# first output and twice into the second; fail makes it exit 1, fail-late exit 1 once it has
# written its first output, and skip-second leaves the second output unwritten.
GENERATOR = '''import sys
from pathlib import Path

if not Path('gen.py').is_file():
    sys.exit(3)
word, *outputs = sys.argv[1:]
if word == 'fail':
    sys.exit(1)
texts = [word + '\\n', word + ' ' + word + '\\n']
if word == 'skip-second':
    texts = texts[:1]
for output, text in zip(outputs, texts):
    Path(output).write_text(text)
    if word == 'fail-late':
        sys.exit(1)
'''

WORDS = 'forty-two\n'
TWICE = 'forty-two forty-two\n'

# A second generator of the same Jamfile, which writes its word into its one output.
AGAIN = 'webcpp.generated again : gen.py : again : generated/again.txt ;\n'


def with_again(jamfile: str) -> str:
    """jamfile with the generator again declared first, so that update-generated runs it first."""
    return jamfile.replace('import webcpp ;\n', 'import webcpp ;\n' + AGAIN)


def snapshot(directory: Path) -> dict[str, bytes]:
    """Every file under directory, by its path relative to it, with its bytes."""
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in sorted(directory.rglob('*')) if path.is_file()}


def add_generator(root: Path, jamfile: str = JAMFILE) -> Path:
    """Adds the library gen, whose test Jamfile declares the generator words, with what it writes
    committed; returns its test directory."""
    test = root / LIBRARY / 'test'
    (test / 'generated/more').mkdir(parents=True)
    (root / LIBRARY / 'build.jam').write_text('project /webcpp/gen ;\n')
    (test / 'Jamfile').write_text(jamfile)
    (test / 'gen.py').write_text(GENERATOR)
    (test / 'generated/words.txt').write_text(WORDS)
    (test / 'generated/more/twice.txt').write_text(TWICE)
    return test


def test_matching_outputs_pass(root: Path) -> None:
    test = add_generator(root)
    before = snapshot(test)
    harness.expect(harness.run_b2(root, '-a', CHECK), True)
    harness.expect(harness.run_b2(root, '-a', LANE), True)
    assert snapshot(test) == before, sorted(snapshot(test))


def test_each_differing_output_fails_by_name(root: Path) -> None:
    test = add_generator(root)
    (test / 'generated/words.txt').write_text('forty-three\n')
    (test / 'generated/more/twice.txt').write_text('forty-two  forty-two\n')
    before = snapshot(test)
    harness.expect(harness.run_b2(root, '-a', CHECK), False,
                   'generated/words.txt: contents differ',
                   'generated/more/twice.txt: contents differ',
                   '`b2 libs/gen/test//update-generated` writes it again')
    # The check writes nothing into the tree, not even when it fails.
    assert snapshot(test) == before, sorted(snapshot(test))


def test_a_missing_committed_output_fails(root: Path) -> None:
    test = add_generator(root)
    (test / 'generated/more/twice.txt').unlink()
    harness.expect(harness.run_b2(root, '-a', CHECK), False,
                   'generated/more/twice.txt: does not exist')


def test_an_output_the_generator_does_not_write_fails(root: Path) -> None:
    test = add_generator(root, JAMFILE.replace('forty-two', 'skip-second'))
    before = snapshot(test)
    result = harness.run_b2(root, '-a', CHECK)
    harness.expect(result, False, 'generated: words: gen.py wrote no ',
                   'twice.txt; it must write each output it is given')
    # Its hint is not the one of an output that differs: update-generated would refuse it too.
    assert 'twice.txt is not what' not in result.stdout, result.stdout[-4000:]
    assert snapshot(test) == before, sorted(snapshot(test))


def test_update_generated_writes_them_in_place(root: Path) -> None:
    test = add_generator(root, with_again(JAMFILE))
    (test / 'generated/words.txt').write_text('stale\n')
    shutil.rmtree(test / 'generated/more')
    harness.expect(harness.run_b2(root, '-a', UPDATE), True, 'generated: words: wrote',
                   'generated: again: wrote')
    assert (test / 'generated/words.txt').read_text() == WORDS
    assert (test / 'generated/more/twice.txt').read_text() == TWICE
    assert (test / 'generated/again.txt').read_text() == 'again\n'
    harness.expect(harness.run_b2(root, '-a', CHECK), True)


def test_a_failing_generator_leaves_every_committed_file(root: Path) -> None:
    # again succeeds before words fails: what again wrote replaces no committed file either.
    test = add_generator(root, with_again(JAMFILE.replace('forty-two', 'fail')))
    (test / 'generated/again.txt').write_text('stale\n')
    harness.expect(harness.run_b2(root, '-a', UPDATE), False, 'gen.py exited with status 1')
    assert (test / 'generated/words.txt').read_text() == WORDS
    assert (test / 'generated/more/twice.txt').read_text() == TWICE
    assert (test / 'generated/again.txt').read_text() == 'stale\n'
    harness.expect(harness.run_b2(root, '-a', CHECK), False, 'gen.py exited with status 1')


def test_a_generator_failing_after_one_output_leaves_every_committed_file(root: Path) -> None:
    test = add_generator(root, JAMFILE.replace('forty-two', 'fail-late'))
    harness.expect(harness.run_b2(root, '-a', UPDATE), False, 'gen.py exited with status 1')
    assert (test / 'generated/words.txt').read_text() == WORDS
    assert (test / 'generated/more/twice.txt').read_text() == TWICE
    assert not list(test.rglob('*.generated')), sorted(test.rglob('*'))


def test_the_lane_is_listed_and_the_ordinary_lanes_skip_it(root: Path) -> None:
    test = add_generator(root)
    (test / 'generated/words.txt').write_text('stale\n')
    result = harness.run_b2(root, '-d0', 'declared-lanes')
    harness.expect(result, True)
    # A generator runs Python, not the original's language: the lane is of the kind programs.
    assert 'gen words libs/gen/test programs\n' in result.stdout, result.stdout
    # The library's ordinary lane builds nothing of it, with the lane or without: it never runs a
    # generator, which may need the network, and so passes over the stale file, which it leaves.
    for jamfile in (JAMFILE, JAMFILE.replace('webcpp.lane words : generated-words ;\n', '')):
        (test / 'Jamfile').write_text(jamfile)
        result = harness.run_b2(root, '-a', 'libs/gen/test')
        harness.expect(result, True)
        for target in ('generated-words', 'update-generated'):
            assert target not in result.stdout, (target, result.stdout[-4000:])
        assert (test / 'generated/words.txt').read_text() == 'stale\n'


def test_no_target_of_it_checks_boost(root: Path) -> None:
    # The check, its lane and update-generated compile nothing, so none of them runs the Jamroot's
    # configuration check of Boost: they build on a machine without Boost, and with it they never
    # compile the check's program. The test project names its library, as a real one does, whose
    # target would otherwise bring the check with it; the lane names no target, then native.
    project = 'project : requirements <library>/webcpp/gen//gen ;\n\n'
    test = add_generator(root, project + JAMFILE)
    (root / LIBRARY / 'build.jam').write_text(
        'project /webcpp/gen ;\n'
        '\n'
        'alias gen : : : : <include>include <library>/boost//headers ;\n')
    text = harness.user_config(root).read_text()
    for jamfile in (JAMFILE, JAMFILE.replace('generated-words ;', 'generated-words : native ;')):
        (test / 'Jamfile').write_text(project + jamfile)
        for config, env_extra in ((text, None), (harness.without_boost(), {'BOOST_ROOT': None})):
            harness.configure(root, config)
            for target in (CHECK, LANE, UPDATE):
                result = harness.run_b2(root, '-a', target, env_extra=env_extra)
                harness.expect(result, True)
                assert 'Boost 1.92 or newer' not in result.stdout, (
                    jamfile, target, result.stdout[-4000:])
    assert (test / 'generated/words.txt').read_text() == WORDS


def test_a_lane_of_programs_still_checks_boost(root: Path) -> None:
    # The skip is exact: a lane's alias leaves the check to what it names, and a program it names
    # checks Boost, with the lane naming no target and naming native.
    project = 'project : requirements <library>/webcpp/gen//gen ;\n\n'
    test = add_generator(root)
    (root / LIBRARY / 'build.jam').write_text(
        'project /webcpp/gen ;\n'
        '\n'
        'alias gen : : : : <include>include <library>/boost//headers ;\n')
    (test / 'program.cpp').write_text('int main() { return 0; }\n')
    text = harness.user_config(root).read_text()
    for targets in ('', ' : native'):
        (test / 'Jamfile').write_text(project + JAMFILE + 'webcpp.run program : program.cpp ;\n'
                                      f'webcpp.lane programs : program{targets} ;\n')
        harness.configure(root, text)
        result = harness.run_b2(root, '-a', f'{LIBRARY}/test//programs')
        harness.expect(result, True, 'Boost 1.92 or newer', '**passed**')
        harness.configure(root, harness.without_boost())
        result = harness.run_b2(root, '-a', f'{LIBRARY}/test//programs',
                                env_extra={'BOOST_ROOT': None})
        harness.expect(result, False, 'Boost 1.92 or newer was not found')


def test_a_wrong_declaration_is_refused(root: Path) -> None:
    test = add_generator(root)
    for jamfile, message in (
            (JAMFILE.replace('gen.py', 'gen.sh'), 'gen.sh is not a Python file'),
            (JAMFILE.replace('gen.py', 'missing.py'), 'libs/gen/test/missing.py does not exist'),
            (JAMFILE + 'webcpp.generated words : gen.py : x : generated/other.txt ;\n',
             'webcpp.generated words is declared twice in libs/gen/test/Jamfile'),
            (JAMFILE + 'webcpp.generated other : gen.py : x : ./generated/words.txt ;\n',
             'webcpp.generated other in libs/gen/test/Jamfile names ./generated/words.txt, which'
             ' webcpp.generated words writes'),
            (JAMFILE.replace('generated/more/twice.txt', 'generated/words.txt'),
             'generated/words.txt twice')):
        (test / 'Jamfile').write_text(jamfile)
        harness.expect(harness.run_b2(root, CHECK), False, message)


CASES = [
    test_matching_outputs_pass,
    test_each_differing_output_fails_by_name,
    test_a_missing_committed_output_fails,
    test_an_output_the_generator_does_not_write_fails,
    test_update_generated_writes_them_in_place,
    test_a_failing_generator_leaves_every_committed_file,
    test_a_generator_failing_after_one_output_leaves_every_committed_file,
    test_the_lane_is_listed_and_the_ordinary_lanes_skip_it,
    test_no_target_of_it_checks_boost,
    test_a_lane_of_programs_still_checks_boost,
    test_a_wrong_declaration_is_refused,
]


if __name__ == '__main__':
    sys.exit(harness.run_cases('generated_jam_test', CASES, sys.argv[1:]))
