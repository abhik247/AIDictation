pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'aidictation'

python = import('python')

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('pkgdatadir', pkgdatadir)
configure_file(
            input: 'aidictation.in',
           output: 'aidictation',
    configuration: conf,
          install: true,
      install_dir: get_option('bindir'),
     install_mode: 'rwxr-xr-x'
)

aidictation_sources = [
    'aidictation/__init__.py',
    'aidictation/main.py',
    'aidictation/models.py',
]

install_data(aidictation_sources, install_dir: moduledir)

aidictation_services = [
    'aidictation/services/__init__.py',
    'aidictation/services/audio_recorder.py',
    'aidictation/services/openai_service.py',
    'aidictation/services/reword_service.py',
    'aidictation/services/settings_service.py',
    'aidictation/services/startup_service.py',
]

install_data(aidictation_services, install_dir: moduledir / 'services')

aidictation_ui = [
    'aidictation/ui/__init__.py',
    'aidictation/ui/floating_widget.py',
    'aidictation/ui/main_window.py',
]

install_data(aidictation_ui, install_dir: moduledir / 'ui')
