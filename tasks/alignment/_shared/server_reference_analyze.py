"""Maintainer smoke submission for the server. Not automatically staged for an Agent."""
import argparse
from official_backend import run_official

parser = argparse.ArgumentParser()
parser.add_argument('--inputs', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
run_official(args.inputs, args.output, device='cpu')
