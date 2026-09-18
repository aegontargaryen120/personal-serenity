"""Preprocessor for Serenity source files.

Handles %import directives that include the contents of other files before
scanning.  The syntax is::

    %import <folder/file>

The file extension is omitted; the preprocessor resolves the path by trying
``.serenity`` and ``.srn`` extensions in order.  Paths are resolved relative
to the directory of the file that contains the import.  Circular imports are
detected and silently skipped.
"""

import os
import re

IMPORT_RE = re.compile(r'^[ \t]*%import\s+<([^>]+)>\s*$', re.MULTILINE)


class PreprocessError(Exception):
    pass


class Preprocessor:
    def __init__(self, base_dir, included=None):
        self.base_dir = os.path.realpath(base_dir)
        self.included = included if included is not None else set()

    def preprocess(self, source, filename=None):
        if filename:
            self.included.add(os.path.realpath(filename))

        while True:
            match = IMPORT_RE.search(source)
            if not match:
                break
            if self._depth_at(source, match.start()) > 0:
                line = source.count('\n', 0, match.start()) + 1
                location = f'{filename}:{line}' if filename else f'line {line}'
                raise PreprocessError(
                    f"%import line in {location} must appear at the top level, "
                    f"not inside a function or block"
                )
            path = match.group(1)
            file_path = self._resolve(path)
            real_path = os.path.realpath(file_path)
            if real_path in self.included:
                source = source[:match.start()] + source[match.end():]
                continue
            self.included.add(real_path)
            with open(file_path, 'r') as f:
                content = f.read()
            sub = Preprocessor(os.path.dirname(file_path), self.included)
            included_content = sub.preprocess(content, file_path)
            source = source[:match.start()] + included_content + source[match.end():]

        return source

    def _resolve(self, path):
        for ext in ('.serenity', '.srn'):
            full_path = os.path.join(self.base_dir, path + ext)
            if os.path.isfile(full_path):
                return full_path
        raise PreprocessError(
            f"cannot resolve '{path}' "
            f"(tried {path}.serenity and {path}.srn)"
        )

    @staticmethod
    def _depth_at(source, target):
        """Return the paren/brace nesting depth at TARGET, ignoring strings
        and comments.  Top-level positions are at depth 0; anything inside a
        function body or block is at depth 1 or greater."""
        depth = 0
        in_string = False
        i = 0
        n = len(source)
        while i < target:
            char = source[i]
            if in_string:
                if char == '\\':
                    i += 2
                    continue
                if char == '"':
                    in_string = False
                i += 1
                continue
            nxt = source[i + 1] if i + 1 < n else ''
            if char == '"':
                in_string = True
                i += 1
                continue
            if char == '/' and nxt == '/':
                newline = source.find('\n', i)
                i = n if newline == -1 else newline + 1
                continue
            if char == '/' and nxt == '*':
                end = source.find('*/', i + 2)
                i = n if end == -1 else end + 2
                continue
            if char == '(' or char == '{':
                depth += 1
            elif char == ')' or char == '}':
                depth -= 1
            i += 1
        return depth
