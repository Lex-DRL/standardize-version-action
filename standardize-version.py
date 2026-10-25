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

import os
import re
import sys
from typing import (
	Any as _A, Callable as _C, Optional as _O, Union as _U,
	Generator, Tuple, NamedTuple,
	Match
)
from warnings import warn


_T_Matcher = _C[[str], _O[Match[str]]]
_T_Path = _U[str, os.PathLike]

_re_padded_int = re.compile(
	r'(?P<pad>0*)'
	r'(?P<int>[1-9][0-9]*)?'
	r'$',
	flags=re.IGNORECASE
).match


class PadInt(NamedTuple):
	number: int
	pad: int = 0

	@staticmethod
	def parse(int_str: str) -> 'PadInt':
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
			return PadInt(0, max(pad - 1, 0))
		return PadInt(int(int_group), pad)

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


class ParsedVersion(NamedTuple):
	numbers: Tuple[PadInt, ...]
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
	def parse(version_str: str) -> 'ParsedVersion':
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

		int_parse = PadInt.parse
		numbers = tuple(
			int_parse(x) for x in
			ParsedVersion.__parse_group_parts(num_group, _re_number_seg)
		)
		suffix_parts = tuple(
			ParsedVersion.__parse_group_parts(suffix_group, _re_suffix_seg, 'suffix')
		)
		return ParsedVersion(numbers, suffix_parts)

# ParsedVersion.parse('v.0.00.01.020.00300a1 aaa')
# ParsedVersion.parse('v0')
# ParsedVersion.parse('0')
# ParsedVersion.parse('v0.001b1')


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


def _write_output(
	output: _T_Path = './TEST_GITHUB_OUTPUT',
	**names_and_values
) -> None:
	"""Write variables to GitHub output."""
	with open(output, "a", encoding="utf-8") as f:
		f.writelines(
			f"{name}={value}\n"
			for name, value in names_and_values.items()
		)


def _cleanup_version_arg(version_arg: _A, sysarg_id=1) -> str:
	ver_str = version_arg
	if not ver_str:
		ver_str = sys.argv[sysarg_id] if len(sys.argv) > sysarg_id else None
	if not ver_str:
		raise ValueError("Version string is required")
	if not isinstance(ver_str, str):
		ver_str = str(ver_str)

	# In case someone passes multiline string:
	non_empty_lines = (
		x for x in (
			seg.strip() for seg in ver_str.splitlines()
		) if x
	)
	try:
		return next(non_empty_lines)
	except StopIteration:
		pass
	raise ValueError(f"Version string contains nothing but whitespaces: {version_arg!r}")


def _cleanup_output_arg(output_arg: _A, sysarg_id=2) -> _T_Path:
	output = output_arg
	if not(output is None or isinstance(output, (str, os.PathLike))):
		output = str(output)
	if not output:
		print(
			f"No output path ({output!r}) is specified as function argument - checking if argument is passed to the script..."
		)
		output = sys.argv[sysarg_id] if len(sys.argv) > sysarg_id else None
	if not output:
		print(
			f"No output path ({output!r}) is passed to the script - checking 'GITHUB_OUTPUT' env var..."
		)
		try:
			output = os.environ.get("GITHUB_OUTPUT")
		except Exception:
			output = None
	if not output:
		raise ValueError(f"Output must be specified in SOME way. Got: {output!r}")
	assert isinstance(output, (str, os.PathLike)) and output

	output_str = str(output)

	# In case someone passes multiline string:
	non_empty_lines = (x for x in output_str.splitlines() if x)
	try:
		first_valid_line = next(non_empty_lines)
	except StopIteration:
		raise ValueError(f"Output path contains nothing but newline characters: {output!r}")
	if not output_str.strip():
		warn(f"Output path contains nothing but whitespaces: {output!r}", RuntimeWarning)
	return first_valid_line if first_valid_line != output_str else output


def main(
	version: str = None, output: _O[_T_Path] = None,
	number_sep='.', parts_sep='-', suffix_internal_sep='-',
	convert_pre=True,
) -> None:
	clean_output = _cleanup_output_arg(output)
	version_str = _cleanup_version_arg(version)
	parsed_version = ParsedVersion.parse(version_str)
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

	# Log all the extracted parts for the action runner:
	print(f"🧩 Parsed version: {version_str!r}")
	print(f"   ├ 🏷️ 'v'      → {v_version}")
	print(f"   ├ full        →  {full_version}")
	print(f"   ├ number      →  {base}")
	print(f"   ├ suffix      → {suffix!r}")
	print(f"   └ is-pre      →  {is_pre_str}")

	_write_output(
		clean_output,
		v=v_version,
		full=full_version,
		number=base,
		suffix=suffix,
		is_pre=is_pre_str,
	)
	print(f"✅ Outputs set")


if __name__ == "__main__":
	main()
