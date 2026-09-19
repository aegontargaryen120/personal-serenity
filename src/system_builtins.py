"""Host-backed system builtins for Serenity.

`shellex` runs a shell command and returns its exit code, and `file` opens a
path for writing, returning a handle that `.write(text)` and `.close()` act
on. The drudgery lives here so both the interpreter and (if it ever grows a
host channel) the bootstrap evaluator share one implementation.
"""

import os
import subprocess
import sys


class SerenityFile:
    """A file opened for writing through the `file` builtin."""

    def __init__(self, path, handle):
        self.path = path
        self.handle = handle
        self.closed = False


def shell_exec(command):
    """Run COMMAND through the shell and return its exit code.

    The command's combined output is replayed onto the program's own stdout so
    it appears in the same place as everything the program prints.
    """
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    text = result.stdout + result.stderr
    if text:
        sys.stdout.write(text)
    return result.returncode


def open_file(path):
    """Open PATH for writing (creating missing parent directories), returning
    a SerenityFile handle."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    return SerenityFile(path, open(path, 'w'))


def write_line(handle, text):
    """Write TEXT (already display-formatted) to a handle, with a trailing
    newline, mirroring Serenity's `println`."""
    handle.handle.write(text)
    handle.handle.write('\n')


def close_file(handle):
    """Flush and close a handle, saving the file."""
    if not handle.closed:
        handle.handle.close()
        handle.closed = True