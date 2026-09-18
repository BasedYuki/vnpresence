"""The script PyInstaller builds.

A frozen build runs its entry script standalone, with no package around it, so
it must not live inside the package and must not use relative imports. Pointing
PyInstaller straight at ``src/vnpresence/__main__.py`` is what broke the first
release - keep this file as the entry point.
"""

from vnpresence.__main__ import main

if __name__ == "__main__":
    main()
