"""Build the small, dependency-free C++ metadata accelerator for Linux."""
import argparse
import os
from pathlib import Path
import subprocess


def build(destination: Path):
    source = Path(__file__).resolve().parents[1] / 'native/desktop/domain_assignment.cpp'
    destination.parent.mkdir(parents=True, exist_ok=True)
    compiler = os.environ.get('NADOC_CXX') or ('/usr/bin/g++' if Path('/usr/bin/g++').exists() else 'g++')
    env = dict(os.environ, PATH='/usr/bin:/bin')
    for name in ('LDFLAGS', 'LD_RUN_PATH', 'LIBRARY_PATH', 'COMPILER_PATH', 'GCC_EXEC_PREFIX'):
        env.pop(name, None)
    subprocess.run([compiler, '-O3', '-std=c++17', '-shared', '-fPIC', '-fno-fast-math', '-fno-exceptions', '-fno-rtti', '-Wl,--as-needed',
                    str(source), '-o', str(destination)], check=True, env=env)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    print(build(parser.parse_args().output))
