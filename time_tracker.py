#!/usr/bin/env python3
"""
Simple tracker for keeping logs on what you did for how long every day.

The tracker creates a folder ~/time_tracker/ with one csv file for each day.
The file lists the start times for each of your tasks and the tracker can print a summary at the end
of the day.
"""
import shutil
import sys
import argparse
import os
import pathlib
import traceback
from datetime import datetime, date, time
import csv
from dataclasses import dataclass, asdict, fields, astuple
from typing import List, Dict, Any


def cmdline_args():
    # Make parser object
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)

    subp = p.add_subparsers(help="Modes", dest="mode")

    read = subp.add_parser("read", help="Print or summarize the time sheet for today")

    write = subp.add_parser("write", help="Add an entry to the time sheet for today")

    write.add_argument("description", default="", type=str,
                       help="Informal description of the task")

    write.add_argument("-s", "--stop",
                       action="store_true",
                       help="Flag the current task as an endpoint, its time will not be counted")

    write.add_argument("-t", "--time", type=str, required=False,
                       help="The time of added line, as HH:MM")

    write.add_argument("-c", "--context", type=str, required=False,
                       help="User-defined context, used to group tasks, defaults to description")

    write.add_argument("-m", "--minor", action="store_true",
                       help="Indicate that the current task is minor, "
                            "its duration will be distributed among other tasks")

    p.add_argument("-v", "--verbose", action="store_true", help="Tooggle verbose")

    return p.parse_args()


@dataclass
class CsvEntry:
    description: str
    start_time: str
    context: str
    is_finish: bool
    is_minor: bool

    def __post_init__(self):
        if type(self.is_finish) == str:
            self.is_finish = self.is_finish == str(True)
        if type(self.is_minor) == str:
            self.is_minor = self.is_minor == str(True)


CsvFields = [fld.name for fld in fields(CsvEntry)]


def filename():
    return pathlib.Path.home() / 'time_tracker' / f'{date.today()}.csv'


def log(verbose: bool, *args):
    if verbose:
        print(*args)


def read_entries() -> List[CsvEntry]:
    if not os.path.exists(filename()):
        return []

    with open(filename(), newline='') as csvread:
        reader = csv.DictReader(csvread, CsvFields)
        return [CsvEntry(**d) for d in list(reader)[1:]]


def write_entries(entries: List[CsvEntry], verbose: bool):
    f = filename()
    time_dir = pathlib.Path(os.path.dirname(f))
    backup_dir = time_dir / 'backup'
    if not os.path.exists(time_dir):
        os.mkdir(time_dir)
    if not os.path.exists(backup_dir):
        os.mkdir(backup_dir)

    if os.path.exists(f):
        backup_path = backup_dir / f'{os.path.basename(f)}.{datetime.now().strftime("%H%M%S")}'
        log(verbose, 'Backing up', f, 'as', backup_path)
        shutil.copy(f, backup_dir / f'{os.path.basename(f)}.{datetime.now().strftime("%H%M%S")}')

    with open(filename(), 'w', newline='') as csvwrite:
        log(verbose, 'Writing modified entries to', f)
        writer = csv.DictWriter(csvwrite, CsvFields)
        writer.writeheader()
        writer.writerows((asdict(entry) for entry in entries))


def add_entry(entries: List[CsvEntry], args) -> List[CsvEntry]:
    timestamp = datetime.combine(date.today(), datetime.strptime(args.time, '%H:%M').time()) \
        if args.time is not None \
        else datetime.now()
    timestr = timestamp.strftime('%H:%M')
    log(args.verbose, "Logging Time", timestr)
    context = args.context if args.context is not None else args.description
    if not args.stop:
        entries.append(CsvEntry(args.description, timestr, context, False, args.minor))
    else:
        entries.append(CsvEntry("", timestr, context, True, args.minor))

    entries.sort(key=lambda e: e.start_time)


def format_table_dict(entries: list[Dict[str, Any]]):
    if len(entries) == 0:
        return ""

    def format(x: Any):
        if type(x) is float:
            return '{:.2f}'.format(x)
        return str(x)

    widths: List[int] = [0] * len(entries[0].items())
    for entry in entries:
        entry_length = (max(len(k), len(format(v))) for k, v in entry.items())
        widths = [max(a, b) for a, b in zip(widths, entry_length)]

    s = ' '.join((k.ljust(w) for k, w in zip(entries[0].keys(), widths))) + "\n"
    s += ' '.join(('-' * w for w in widths)) + "\n"
    for entry in entries:
        s += ' '.join((format(e).ljust(w) for e, w in zip(entry.values(), widths))) + "\n"
    return s


def format_table(entries: List[Any]):
    return format_table_dict([asdict(e) for e in entries])


def print_summary(entries: List[CsvEntry]):
    def time_to_minutes(t: str):
        parsed = datetime.strptime(t, '%H:%M')
        return parsed.minute + 60 * parsed.hour

    time_minutes = [time_to_minutes(e.start_time) for e in entries]
    now = datetime.now()
    time_minutes.append(now.minute + 60 * now.hour)
    durations = [end - start for start, end in zip(time_minutes[:-1], time_minutes[1:])]
    total_time = sum(((d if not e.is_finish else 0) for d, e in zip(durations, entries)))
    major_time = sum(
        ((d if not e.is_finish and not e.is_minor else 0) for d, e in zip(durations, entries)))
    stretch_factor = float(total_time) / major_time

    @dataclass
    class MajorEntry:
        description: str
        original_minutes: int
        minutes: float
        hours: float
        context: str

    major_entries: List[MajorEntry] = [
        MajorEntry(e.description, d, d * stretch_factor, d * stretch_factor / 60, e.context) for
        e, d in zip(entries, durations) if not e.is_minor and not e.is_finish
    ]

    contexts = set(e.context for e in major_entries)

    @dataclass
    class ContextEntry:
        context: str
        original_minutes: int
        minutes: float
        hours: float
        tasks: List[str]

    contextEntries = [
        ContextEntry(c,
                     sum(e.original_minutes for e in major_entries if e.context == c),
                     sum(e.minutes for e in major_entries if e.context == c),
                     sum(e.hours for e in major_entries if e.context == c),
                     list(set(e.description for e in major_entries if e.context == c))
                     )
        for c in contexts
    ]

    print("Major Entries")
    print(format_table(major_entries))

    print("Sums across contexts")
    print(format_table(contextEntries))

    print("Total hours: {:.2f}".format(sum(e.hours for e in major_entries)))


def print_entries(entries: List[CsvEntry]):
    print(format_table(entries))
    print_summary(entries)


if __name__ == '__main__':
    try:
        args = cmdline_args()
        log(args.verbose, "Arguments: ", args)
        log(args.verbose, "Opening", filename())
        entries = read_entries()
        entries.sort(key=lambda e: e.start_time)
        log(args.verbose, f"Entries\n{format_table(entries)}")
        if args.mode == 'write':
            add_entry(entries, args)
            print(f"New Entries:\n{format_table(entries)}")
            write_entries(entries, args.verbose)
        elif args.mode == 'read':
            print_entries(entries)

    except Exception as e:
        print(f'Error {e}')
        traceback.print_exc()
