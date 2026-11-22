#!/usr/bin/env python3
"""
Parses version and writes GitHub Action outputs with it turned into pythonic SemVer format.
"""

from standard_version import StandardVersion

from dataclasses import dataclass as _dataclass

from _shared_utils import _cleanup_as_single_line, _EnvInputsABC, GithubOutput


def _validate_input_version(input_version) -> str:
	ver_str = input_version
	if not ver_str:
		raise ValueError("Input-version string is required")
	if not isinstance(ver_str, str):
		raise TypeError(f"Input-version isn't a string: {ver_str!r}")
	ver_str = _cleanup_as_single_line(ver_str)
	if not ver_str:
		raise ValueError(f"Input-version string contains nothing but whitespaces: {input_version!r}")
	return ver_str


@_dataclass
class EnvInputs(_EnvInputsABC):
	"""Script 'arguments' passed as env-vars (for security reasons)."""
	input_version: str

	def __post_init__(self):
		self.input_version = _validate_input_version(self.input_version)


def main(github_output_env: str = 'GITHUB_OUTPUT') -> None:
	env_args = EnvInputs.from_env()
	# env_args.print()
	print(f"🧩 Parsed version: {env_args.input_version!r}")

	outputs = StandardVersion.from_string(env_args.input_version)
	is_pre_str = 'true' if outputs.is_pre else 'false'
	v_full = outputs.v_full
	full = outputs.full

	# Log all the extracted parts for the action runner:
	print(f"   ├ 🏷️ 'v'      → {v_full}")
	print(f"   ├ full        →  {full}")
	print(f"   ├ number      →  {outputs.numeric}")
	print(f"   ├ suffix      → {outputs.suffix!r}")
	print(f"   └ is-pre      →  {is_pre_str}")

	GithubOutput(github_output_env=github_output_env, do_print=False).set(
		v=v_full,
		full=full,
		number=outputs.numeric,
		suffix=outputs.suffix,
		is_pre=is_pre_str,
	)

	print(f"✅ Outputs set")


if __name__ == "__main__":
	main()
