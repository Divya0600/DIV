# PyInstaller hook file for renderers package
from PyInstaller.utils.hooks import collect_all

# Collect all modules and data files from renderers package
datas, binaries, hiddenimports = collect_all('renderers')

# Explicitly add the renderer modules
hiddenimports += [
    'renderers.nuke_renderer',
    'renderers.silhouette_renderer',
    'renderers.__init__'
]