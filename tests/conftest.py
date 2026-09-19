"""Keep scaffold tests offline while exercising their real CLI/parser behavior."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / 'skills/skill-smith/scripts/scaffold_skill.py'


@pytest.fixture(autouse=True)
def offline_scaffold_transport(monkeypatch, tmp_path_factory):
    """Only kit download is faked; fixture kits contain the pinned tool source."""
    original_run = subprocess.run
    scratch = tmp_path_factory.getbasetemp().resolve()

    def intercept(args, **kwargs):
        if not isinstance(args, (list, tuple)) or len(args) < 2 or Path(args[1]).resolve() != SCAFFOLD:
            return original_run(args, **kwargs)
        import scaffold_skill
        output, error = io.StringIO(), io.StringIO()

        def git_transport(command, **options):
            destination = Path(options['cwd']).resolve()
            assert destination.is_relative_to(scratch), 'scaffold escaped test workspace'
            if command[:3] == ['git', 'submodule', 'add']:
                kit = command[-1]
                assert kit in ('guards', 'style')
                source = ROOT / kit
                assert (source / 'tools').is_dir(), 'initialize pinned test dependency submodules'
                target = destination / kit
                shutil.copytree(source, target, ignore=shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache'))
                (target / '.git').write_text('gitdir: ../.git/modules/' + kit + '\n')
                with (destination / '.gitmodules').open('a', encoding='utf-8') as stream:
                    stream.write(f'[submodule "{kit}"]\n\tpath = {kit}\n\turl = {command[-2]}\n')
                return subprocess.CompletedProcess(command, 0, '', '')
            assert command[:2] in (['git', 'init'], ['git', 'config']), 'unexpected external scaffold transport'
            return original_run(command, **options)

        with patch.object(sys, 'argv', [str(SCAFFOLD), *args[2:]]), \
                patch.object(subprocess, 'run', git_transport), \
                patch.dict(os.environ, kwargs.get('env', dict(os.environ)), clear=True), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                code = scaffold_skill.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
                if exc.code and not isinstance(exc.code, int):
                    print(exc.code, file=error)
        return subprocess.CompletedProcess(args, code, output.getvalue(), error.getvalue())

    monkeypatch.setattr(subprocess, 'run', intercept)
