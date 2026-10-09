# SPDX-License-Identifier: GPL-3.0-or-later
blueprint_sources = files(
    'agent/ui/window.blp',
    'agent/ui/preferences.blp',
)

blueprints = custom_target(
    'blueprints',
    input: blueprint_sources,
    output: [
        'window.ui',
        'preferences.ui',
    ],
    command: [
        find_program('blueprint-compiler'),
        'batch-compile',
        '@OUTDIR@',
        '@CURRENT_SOURCE_DIR@' / 'agent/ui',
        '@INPUT@',
    ],
)

gnome.compile_resources(
    'agent',
    'agent.gresource.xml',
    gresource_bundle: true,
    install: true,
    install_dir: pkgdatadir,
    dependencies: blueprints,
)

conf = configuration_data()
conf.set('PYTHON', py_installation.full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
    input: 'agent.in',
    output: 'agent',
    configuration: conf,
    install: true,
    install_dir: get_option('bindir'),
    install_mode: 'r-xr-xr-x',
)

install_subdir(
    'agent',
    install_dir: pkgdatadir,
    exclude_files: [
        'ui/window.blp',
        'ui/preferences.blp',
    ],
    exclude_directories: [
        '__pycache__',
        'core/__pycache__',
        'ui/__pycache__',
    ],
)
