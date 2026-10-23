"""Worker launcher. Receives one X/Y packet and code; never an oracle path or score authority."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--submission', required=True, type=Path)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.chdir(args.submission)
    os.execv(sys.executable, [sys.executable, '-B', str(args.submission / 'analyze.py'),
                             '--inputs', str(args.inputs), '--output', str(args.output)])


if __name__ == '__main__':
    main()
