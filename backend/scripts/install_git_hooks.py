"""Install the project's git hooks on this computer (No. 150, loop 4).

    cd backend
    .venv/Scripts/python.exe scripts/install_git_hooks.py

Copies scripts/git-hooks/pre-push into the repository's .git/hooks, so every
`git push` from this computer runs the golden cases first and is stopped if
one fails. Git does not copy hooks with a clone, so run this once on each
computer that pushes. Replaces only a pre-push hook this script installed;
any other is kept and reported.
"""

import shutil
import stat
import subprocess
import sys
from pathlib import Path

MARK = "Loop 4 (PROJECT-REGISTER No. 150)"


def main() -> int:
    here = Path(__file__).resolve().parent
    source = here / "git-hooks" / "pre-push"
    hooks = Path(subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"], cwd=here, check=True,
        capture_output=True, text=True).stdout.strip())
    if not hooks.is_absolute():
        hooks = (here / hooks).resolve()
    target = hooks / "pre-push"
    if target.exists() and MARK not in target.read_text(encoding="utf-8",
                                                        errors="replace"):
        print(f"A different pre-push hook is already at {target} — left as "
              f"it is. Merge {source} into it by hand.")
        return 1
    hooks.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
