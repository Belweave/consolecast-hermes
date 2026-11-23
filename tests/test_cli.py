from __future__ import annotations

import argparse


def parser(pkg):
    p = argparse.ArgumentParser(prog="hermes consolecast")
    pkg.cli.setup_parser(p)
    return p


def test_status_and_doctor(pkg, fake_app, capsys):
    p = parser(pkg)
    args = p.parse_args(["status"])
    assert args.func(args) == 0
    assert capsys.readouterr().out.startswith("Console Cast 0.3.2")
    args = p.parse_args(["doctor"])
    args.func(args)
    out = capsys.readouterr().out
    assert "Ready to stream" in out or "Not ready yet" in out


def test_no_subcommand_takes_a_key(pkg):
    p = parser(pkg)
    subs = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    assert set(subs.choices) == {"status", "doctor", "setup"}
