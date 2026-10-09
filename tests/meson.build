# SPDX-License-Identifier: GPL-3.0-or-later
# `meson test` runs the unit suite whenever pytest is found. A dev build
# (-Ddev=true) requires pytest and adds the lint suite, whose tools it also
# requires, so a contributor can't get a green run without every check.

dev = get_option('dev')
source_root = meson.project_source_root()

pytest = find_program('pytest', required: dev)
if pytest.found()
    test('pytest', pytest, workdir: source_root, suite: 'unit', timeout: 300)
endif

if dev
    if not meson.version().version_compare('>= 1.5')
        error('A dev build needs Meson 1.5 or newer, for meson format.')
    endif
    ruff = find_program('ruff')
    basedpyright = find_program('basedpyright')
    blueprint_compiler = find_program('blueprint-compiler')
    meson_exe = find_program('meson')

    test(
        'ruff check',
        ruff,
        args: ['check', source_root],
        workdir: source_root,
        suite: 'lint',
    )
    test(
        'ruff format',
        ruff,
        args: ['format', '--check', source_root],
        workdir: source_root,
        suite: 'lint',
    )
    test(
        'basedpyright',
        basedpyright,
        args: ['--pythonpath', py_installation.full_path()],
        workdir: source_root,
        suite: 'lint',
        timeout: 300,
    )
    test(
        'blueprint format',
        blueprint_compiler,
        args: ['format', blueprint_sources],
        suite: 'lint',
    )
    test(
        'meson format',
        meson_exe,
        args: ['format', '--check-only', '--recursive', source_root],
        suite: 'lint',
    )

    run_target(
        'fix',
        command: [
            find_program(source_root / 'build-aux' / 'fix.sh'),
            ruff,
            blueprint_compiler,
            meson_exe,
        ],
    )
endif
