# encoding: utf-8
"""
"""
import typing as _t
from typing import Any as _A, Optional as _O, Union as _U

from abc import ABCMeta as __ABCMeta
from collections import deque
from dataclasses import dataclass as _dataclass, fields as _fields
import os as _os
import uuid as _uuid


LOCAL_TESTING = False
# LOCAL_TESTING = True


def _cleanup_as_single_line(string: str | None) -> str:
	"""Ensure the given string is a single line one."""
	if not string:
		return ''
	parts = (x.strip() for x in str(string).strip().splitlines())
	parts = (x for x in parts if x)
	try:
		return next(parts)
	except StopIteration:
		return ''


def _is_true_str(str_bool: _O[str]) -> bool:
	"""Convert GitHub-action's "boolean" string into an actual bool."""
	str_bool = '' if str_bool is None else str(str_bool)
	str_bool = str_bool.strip()
	if not str_bool or str_bool.lower() == 'false':
		return False
	return True


def _check_env_var_name(name: _O[str], what: str = 'an env-var') -> str:
	"""Ensure the given name is a proper env-var."""
	name = '' if name is None else str(name)
	if not name:
		raise ValueError(f"Empty name for {what}: {name!r}")
	return name


def _get_env_var(name: str, what: str = 'an env-var', default=None) -> str:
	"""Read environment variable."""
	name = _check_env_var_name(name, what)
	value = _os.environ.get(name, default)
	return str(value) if value else ''


@_dataclass
class GithubOutput:
	"""Service class: performs safe/secure writes to GITHUB_OUTPUT file."""
	github_output_env: str = 'GITHUB_OUTPUT'
	do_print: bool = True
	print_indent: str = '  '
	multiline_delimiter: str = 'EOF'

	def __format_single_output(self, name: str, value: str) -> str:
		assert isinstance(name, str) and name
		value = '' if value is None else str(value)

		value_lines = value.splitlines()
		if len(value_lines) < 2:
			# Single-line value
			value = value_lines[0] if value_lines else ''
			return f'{name}={value}\n'

		# Multi-line value
		delimiter = self.multiline_delimiter
		# Prevent code injections:
		while delimiter in value:
			delimiter = _uuid.uuid4().hex  # random, cannot be guessed/injected
			delimiter = f'EOF{delimiter}'
		return (
			f'{name}<<{delimiter}\n'
			f'{value}\n'
			f'{delimiter}\n'
		)

	def set(self, **outputs):
		"""Set outputs in GITHUB_OUTPUT file."""
		if not outputs:
			return

		output_path = _get_env_var(
			self.github_output_env, 'github-output env-var',
			default='GITHUB_OUTPUT' if LOCAL_TESTING else None
		)
		if not output_path:
			raise ValueError(f"Empty path for GITHUB_OUTPUT file: {output_path!r}")

		output_lines = [
			self.__format_single_output(name, value)
			for name, value in outputs.items()
		]
		if self.do_print:
			print(f"Setting outputs to: {output_path!r}")
		with open(output_path, 'at', encoding='utf-8') as f:
			f.writelines(output_lines)

		if not self.do_print:
			return
		print_indent = self.print_indent
		print("Outputs are set:")
		for name, value in outputs.items():
			print(f"{print_indent}{name}: {value!r}")


class _EnvInputsABC(metaclass=__ABCMeta):
	"""
	Service base class for dataclasses which define the inputs passed to a python script as env-vars.

	This way is preferred over passing them as shelf arguments, since inputs might contain
	malicious code injection. When passed from action runner as ``env: my_var: ${{ inputs.my-input }}``,
	it's no longer a problem.
	"""
	@staticmethod
	def __cleanup_field_name(name) -> str:
		if not (isinstance(name, str) and name):
			raise ValueError(f"Invalid name for an env-var: {name!r}")
		return _cleanup_as_single_line(name)

	@staticmethod
	def __cleanup_expected_type(_type, name: str) -> type:
		if not isinstance(_type, type):
			raise TypeError(f"Unknown type for {name} env-var: {_type}")
		if not callable(_type):
			raise TypeError(f"Type for {name} env-var doesn't support instance creation: {_type}")
		return _type

	@classmethod
	def from_env(cls: callable) -> '_EnvInputsABC':
		kwargs = dict()
		for field in _fields(cls):
			name = cls.__cleanup_field_name(field.name)
			_type = cls.__cleanup_expected_type(field.type, name)
			raw_value = _get_env_var(name, what=name)
			value = _is_true_str(raw_value) if issubclass(_type, bool) else _type(raw_value)
			kwargs[name] = value
		return cls(**kwargs)

	def print(self, prefix: str = 'Using arguments:', arg_prefix: str = '->'):
		lines: _t.Deque[str] = deque()
		for field in _fields(self):
			name = field.name
			value = getattr(self, name)
			lines.append(f'{arg_prefix}{name!r}: {value!r}')
		if not lines:
			return
		if prefix:
			lines.appendleft(str(prefix))
		joined = '\n'.join(lines)
		print(f'\n{joined}')
