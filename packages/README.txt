Place offline web UI assets in packages/web_assets before running the installer.

Required files (from an internet-connected machine):
- react.production.min.js (React 18 UMD)
- react-dom.production.min.js (ReactDOM 18 UMD)
- babel.min.js (Babel Standalone)
- tailwind.min.css (precompiled Tailwind CSS)

After copying, run the server/worker install scripts. They call packages/install_offline_packages.bat which copies these files into web/vendor for offline UI.
MISSING: redis wheel file

To complete offline setup, download:
pip download redis --only-binary=:all:

Then run: install_offline_packages.bat