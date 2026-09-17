"""Every string the agent prints must survive a Windows console.

The agent logs to a console and to agent.log, and a Windows console is CP-1252
unless somebody has changed it. A UTF-8 em dash written there arrives as three
mojibake characters, so the message an operator reads while something is
already broken looks like a second fault on top of the first. This was real:

    ERROR agent: Could not listen on 127.0.0.1:8080 a?" is another agent
    already running?

Comments are not checked. They are never printed, and the C++ sources use
typographic dashes in prose throughout - restricting those would be tidiness
rather than a defect. Only string literals reach a terminal.

This lives here, in the Python suite, for the same reason test_config_file.py
reads the agent's ConfigFile.cpp: the check is cheap in Python, and the agent's
own tests would have to grow a source scanner to do it.
"""
import re
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parents[2] / "agent"

# Anything between double quotes holding a byte above ASCII. Deliberately
# simple: it over-matches on a line that mixes a string with a commented dash,
# which fails safe - the fix for a false positive is to use ASCII anyway.
NON_ASCII_IN_STRING = re.compile(r'"[^"\n]*[^\x00-\x7f][^"\n]*"')


def agent_sources():
    for pattern in ("*.cpp", "*.h"):
        for path in AGENT.rglob(pattern):
            if "build" not in path.parts:
                yield path


def test_the_agent_sources_are_where_they_are_expected():
    """A moved tree would make the scan below pass by finding nothing."""
    sources = list(agent_sources())

    assert len(sources) >= 20, f"only found {len(sources)} agent sources"


@pytest.mark.parametrize(
    "source", sorted(agent_sources(), key=str), ids=lambda p: p.name
)
def test_no_printed_string_carries_a_character_a_console_cannot_show(source):
    offenders = [
        (number, line.strip())
        for number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), 1
        )
        if NON_ASCII_IN_STRING.search(line)
    ]

    assert offenders == [], "\n".join(
        f"{source.name}:{number}: {line}" for number, line in offenders
    )
