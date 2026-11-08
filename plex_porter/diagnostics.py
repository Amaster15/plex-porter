"""Local, rotating operation logs. Secrets are redacted before writing."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import threading
from . import __version__


def redact(value):
    text = str(value)
    text = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/=._-]+', r'\1 [REDACTED]', text)
    # Handle query strings, JSON, XML attributes, and URL-encoded query strings.
    names = r"(?:X-Plex-Token|PlexOnlineToken|token|password|passwd|claimToken|Authorization)"
    text = re.sub(rf'(?i)({names}[\"\x27]?\s*[:=]\s*)([\"\x27])[^\"\x27]*\2',
                  r'\1"[REDACTED]"', text)
    text = re.sub(rf'(?i)({names}(?:%22|[\"\x27])?\s*(?:=|:|%3[dD]|%3[aA])\s*(?:%22|[\"\x27])?)([^\s&<>\"\x27]+)',
                  r'\1[REDACTED]', text)
    text = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/=._-]+', r'\1 [REDACTED]', text)
    text = re.sub(r'\bclaim-[A-Za-z0-9_-]+', '[REDACTED]', text)
    return text


class SessionLog:
    def __init__(self, directory=None):
        if directory is None:
            base = Path(os.environ.get('LOCALAPPDATA', Path.home())) if os.name == 'nt' else Path.home() / '.local/state'
            directory = base / 'plex-porter/logs'
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'operations.log'
        fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)
        self.handler = RotatingFileHandler(self.path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        self.lock = threading.Lock()
        self.write(f'Plex Porter {__version__} started')

    def write(self, message, error=False):
        record = logging.LogRecord('plex-porter', logging.ERROR if error else logging.INFO,
                                   '', 0, redact(message), (), None)
        with self.lock:
            self.handler.handle(record)
            self.path.chmod(0o600)

    def save(self, target):
        target = Path(target)
        sources = [self.path.with_name(self.path.name + f'.{i}') for i in (3, 2, 1)] + [self.path]
        if target.resolve() in [p.resolve() for p in sources]:
            raise ValueError('Choose a filename outside the active log files.')
        with self.lock:
            self.handler.flush()
            with target.open('w', encoding='utf-8') as out:
                out.write('Plex Porter support report. Paths and filenames may contain personal information.\n')
                for source in sources:
                    if source.exists():
                        out.write(redact(source.read_text(encoding='utf-8')))

    def close(self):
        self.handler.close()
