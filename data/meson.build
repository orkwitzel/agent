# SPDX-License-Identifier: GPL-3.0-or-later
desktop_file = i18n.merge_file(
    input: configure_file(
        input: app_id + '.desktop.in',
        output: app_id + '.desktop.in',
        configuration: {'APP_ID': app_id},
    ),
    output: app_id + '.desktop',
    type: 'desktop',
    po_dir: '../po',
    install: true,
    install_dir: get_option('datadir') / 'applications',
)

desktop_utils = find_program('desktop-file-validate', required: false)
if desktop_utils.found()
    test('Validate desktop file', desktop_utils, args: [desktop_file])
endif

appstream_file = i18n.merge_file(
    input: configure_file(
        input: app_id + '.metainfo.xml.in',
        output: app_id + '.metainfo.xml.in',
        configuration: {'APP_ID': app_id},
    ),
    output: app_id + '.metainfo.xml',
    po_dir: '../po',
    install: true,
    install_dir: get_option('datadir') / 'metainfo',
)

appstreamcli = find_program('appstreamcli', required: false, disabler: true)
test(
    'Validate appstream file',
    appstreamcli,
    args: ['validate', '--no-net', '--explain', appstream_file],
)

install_data(
    app_id + '.gschema.xml',
    install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

compile_schemas = find_program(
    'glib-compile-schemas',
    required: false,
    disabler: true,
)
test(
    'Validate schema file',
    compile_schemas,
    args: ['--strict', '--dry-run', meson.current_source_dir()],
)

install_subdir('icons', install_dir: get_option('datadir'))
