#!/usr/bin/env python3
"""
Parses version and writes GitHub Action outputs with it turned into pythonic SemVer format.

Handles:
- Any number of version segments (1.0, 1.2.3, 1.2.3.4, ...)
- Optional 'v' prefix.
- Preserves padded ints in main version part (v0.001.023)
- Optional suffix:
  - separator is always normalized to '-': v1.2.3-alpha, not v1.2.3.alpha
  - PIP pre-releases (a1, b2, rc3) are converted to nicer alpha1, beta1, RC1.
"""

from typing import (
	Any as _A, Callable as _C, Optional as _O, Union as _U,
	Generator, Tuple, NamedTuple,
	Match
)

from dataclasses import dataclass as _dataclass, asdict as _asdict
import os
import re

from _shared_utils import _cleanup_as_single_line, _EnvInputsABC, GithubOutput


_T_Matcher = _C[[str], _O[Match[str]]]
_T_Path = _U[str, os.PathLike]

_re_padded_int = re.compile(
	r'(?P<pad>0*)'
	r'(?P<int>[1-9][0-9]*)?'
	r'$',
	flags=re.IGNORECASE
).match


class _PadInt(NamedTuple):
	number: int
	pad: int = 0

	@staticmethod
	def parse(int_str: str) -> '_PadInt':
		assert isinstance(int_str, str) and int_str.strip()
		match = _re_padded_int(int_str)
		if not match:
			raise ValueError(f'Invalid number-string: {int_str!r}')
		pad = len(match.group('pad'))
		try:
			int_group = match.group('int')
		except IndexError:
			int_group = None
		if not int_group:
			return _PadInt(0, max(pad - 1, 0))
		return _PadInt(int(int_group), pad)

	def format(self) -> str:
		pad_str = '0' * max(self.pad, 0)
		return f'{pad_str}{self.number}'


_re_whole_version = re.compile(  # Whole version string -> num/suffix groups
	r'(?:[vV][^a-zA-Z0-9]*)?'  # v + optional punctuation
	r'(?P<num>'  # the main version number group
	r'[0-9]+'  # first part
	r'(?:[^a-zA-Z0-9]+[0-9]+)*'  # all other numeric parts with separators
	r')'
	r'[^a-zA-Z0-9]*'  # optional suffix-separator
	r'(?P<suffix>'
	r'[a-zA-Z]+'
	r'.*?'
	r')?$',
	flags=re.IGNORECASE
).match
# Python's re.match acts weirdly with groups
# when a (possibly recurring) group is inside non-capturing optional one.
# Thus, we have to extract segments in a loop, one by one:
_re_number_seg = re.compile(  # Parse only numeric group into actual numbers
	r'(?P<first>[0-9]+)'  # First number
	r'(?:'
	r'[^a-zA-Z0-9]+'  # Any non-ASCII separator
	r'(?P<remainder>.*?)'  # The remainder
	r')?$',
	flags=re.IGNORECASE
).match
_re_suffix_seg = re.compile(  # Parse only suffix group into ASCII parts
	r'(?P<first>[a-zA-Z0-9]+)'
	r'(?:'
	r'[^a-zA-Z0-9]+'  # Any non-ASCII separator
	r'(?P<remainder>.*?)'  # The remainder
	r')?$',
	flags=re.IGNORECASE
).match


class _ParsedVersion(NamedTuple):
	numbers: Tuple[_PadInt, ...]
	suffix: Tuple[str, ...] = tuple()

	@staticmethod
	def __parse_group_parts(
		group: str, seg_extractor: _T_Matcher,
		what='base version'
	) -> Generator[str, _A, None]:
		while group:
			match = seg_extractor(group)
			if not match:
				raise ValueError(f'Invalid remainder of {what}: {group!r}')
			yield match.group('first')
			try:
				group = match.group('remainder')
			except IndexError:
				break

	@staticmethod
	def parse(version_str: str) -> '_ParsedVersion':
		# version_str = 'v.1.2.3a1 aaa'
		# version_str = 'v.1.2.3'
		assert isinstance(version_str, str) and version_str.strip()
		match = _re_whole_version(version_str)
		if not match:
			raise ValueError(f'Invalid version string: {version_str!r}')
		num_group = match.group('num')
		try:
			suffix_group = match.group('suffix')
		except IndexError:
			suffix_group = ''

		int_parse = _PadInt.parse
		numbers = tuple(
			int_parse(x) for x in
			_ParsedVersion.__parse_group_parts(num_group, _re_number_seg)
		)
		suffix_parts = tuple(
			_ParsedVersion.__parse_group_parts(suffix_group, _re_suffix_seg, 'suffix')
		)
		return _ParsedVersion(numbers, suffix_parts)

# _ParsedVersion.parse('v.0.00.01.020.00300a1 aaa')
# _ParsedVersion.parse('v0')
# _ParsedVersion.parse('0')
# _ParsedVersion.parse('v0.001b1')


# https://peps.python.org/pep-0440/#pre-releases
_pre_v_converters: dict[str, _T_Matcher] = {
	formatter: re.compile(pattern, flags=re.IGNORECASE).match
	for formatter, pattern in (
		('alpha{}', r'a(?:lpha)?([0-9]*)$'),
		('beta{}', r'b(?:eta)?([0-9]*)$'),
		('RC{}', r'r?c([0-9]*)$'),
	)
}
_pre_v_matcher = re.compile(
	r'(?:alpha|beta|RC)[0-9]*$',
	flags=re.IGNORECASE
).match


def _convert_pre_v(suffix: str) -> str:
	for format_str, matcher in _pre_v_converters.items():
		match = matcher(suffix)
		if not match:
			continue
		try:
			number = match.group(1)
		except IndexError:
			number = ''
		return format_str.format(number)
	return suffix


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


@_dataclass
class Outputs:
	v: str
	full: str
	number: str
	suffix: str
	is_pre: str  # Not a bool, but "GitHub-var-bool-like" string

	@classmethod
	def from_input_version(
		cls,
		input_version: str,
		number_sep='.', parts_sep='-', suffix_internal_sep='-', convert_pre=True,
	) -> 'Outputs':
		parsed_version = _ParsedVersion.parse(input_version)
		numbers = parsed_version.numbers
		suffix_parts = parsed_version.suffix

		suffix_converted = tuple(_convert_pre_v(x) for x in suffix_parts)
		is_pre_str = 'true' if (
			suffix_converted and _pre_v_matcher(suffix_converted[0])
		) else 'false'

		base = number_sep.join(pad_i.format() for pad_i in numbers)
		suffix = suffix_internal_sep.join(
			suffix_converted if convert_pre else suffix_parts
		)

		full_version = f'{base}{parts_sep}{suffix}' if suffix else base
		v_version = f'v{full_version}'

		return cls(v=v_version, full=full_version, number=base, suffix=suffix, is_pre=is_pre_str)


def main(github_output_env: str = 'GITHUB_OUTPUT') -> None:
	env_args = EnvInputs.from_env()
	# env_args.print()
	print(f"🧩 Parsed version: {env_args.input_version!r}")

	outputs = Outputs.from_input_version(env_args.input_version)

	# Log all the extracted parts for the action runner:
	print(f"   ├ 🏷️ 'v'      → {outputs.v}")
	print(f"   ├ full        →  {outputs.full}")
	print(f"   ├ number      →  {outputs.number}")
	print(f"   ├ suffix      → {outputs.suffix!r}")
	print(f"   └ is-pre      →  {outputs.is_pre}")

	GithubOutput(github_output_env=github_output_env, do_print=False).set(
		**_asdict(outputs)
	)

	print(f"✅ Outputs set")


if __name__ == "__main__":
	main()
