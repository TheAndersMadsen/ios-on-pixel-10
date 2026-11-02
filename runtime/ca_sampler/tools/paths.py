"""Locate the checkout by its Git marker; keep generated material in research."""
import importlib.util
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def repository(start=ROOT):
    for candidate in (start, *start.parents):
        # .git can be a directory or a worktree's gitfile.
        if (candidate / '.git').exists():
            return candidate
    raise RuntimeError('place ca_sampler inside a Git checkout')


REPO = repository()
DEFAULT_OUTPUT = REPO / 'research/ca_sampler'
DEFAULT_BINARY = REPO / 'research/ios26-gpugl-r1/x/QuartzCore'
DEFAULT_DISASSEMBLY = REPO / 'research/ios26-root-r1/apple/dis/QuartzCore.s'
DEFAULT_PACSTRIP = REPO / 'research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py'
DEFAULT_MKOVERLAY = REPO / 'research/ios26-overlay-r1/tools/mkoverlay.py'
DEFAULT_XNU = REPO / 'research/ios26-release-r1/work/xnu'
DEFAULT_BASE = REPO / 'research/ios26-gpugl-r1/phone/p5-merged-r2-gltrack.ovl'
DEFAULT_BASE_SHA = '61c38161efd809bdac15f9f167e5431a4f116b54bf42c7280411480fa37bea2a'


def generated(path):
    path = Path(path).resolve()
    research = (REPO / 'research').resolve()
    if path == research or not path.is_relative_to(research):
        raise ValueError('generated output must be below this checkout\'s ignored research/')
    return path


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, Path(path).resolve())
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj
