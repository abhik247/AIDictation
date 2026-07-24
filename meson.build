project('aidictation',
          version: '0.1.0',
    meson_version: '>= 1.0.0',
  default_options: [ 'warning_level=2', 'werror=false' ],
)

desktop_file = 'com.github.abhik247.AIDictation.desktop'
install_data(desktop_file, install_dir: get_option('datadir') / 'applications')

metainfo_file = 'com.github.abhik247.AIDictation.metainfo.xml'
install_data(metainfo_file, install_dir: get_option('datadir') / 'metainfo')

subdir('src')
