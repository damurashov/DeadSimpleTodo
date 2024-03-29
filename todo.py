#!/usr/bin/python3
# -*- coding: UTF-8 -*-

import sys
import os
from simple_term_menu import TerminalMenu
from pathlib import Path
from dataclasses import dataclass, field
import datetime
from parsedatetime import Calendar
import json
from dateutil.parser import parse as date_parse
import tabulate
import colorama
import re
from generic import Log
import shutil
import textwrap
import gzip


TIME_FORMAT = "%Y-%m-%d %H:%M"
DUMP_TIME_FORMAT = "%Y%m%d%H%M%S"
CURRENT_TIME = datetime.datetime.strftime(datetime.datetime.now(), TIME_FORMAT)
DUMP_DURRENT_TIME = datetime.datetime.strftime(datetime.datetime.now(), DUMP_TIME_FORMAT)
VERSION = "1.5.0"
tabulate.PRESERVE_WHITESPACE = True


def list_remove_item(l, item):
    try:
        l.remove(item)
    except ValueError:
        pass

def _dict_try_get_value(d, key):
    try:
        return d[key]
    except KeyError:
        return None


class Color:

    SEARCH_HIGHLIGHT = [[colorama.Back.CYAN, colorama.Fore.BLACK], [colorama.Back.RESET, colorama.Fore.RESET]]
    HELP_ENTRY = [colorama.Style.BRIGHT]

    @staticmethod
    def colorize_wrap(text, *colors):
        """
        Accepts 2 types of sequences:
        1. [color, color, color]
        2. [[color, color,...], [color, color]] - The second sequence will be applied at the end
        """
        assert 2 >= len(colors) > 0
        assert type(colors[0]) in [list, type(colorama.Fore.BLACK)]

        if type(colors[0]) is list:
            return "".join(colors[0]) + text + "".join(colors[1])
        else:
            return "".join(colors) + text + colorama.Style.RESET_ALL

    # This set of rules may be extended w/ any formatting code whatsoever
    RULES = [
        [r"IMPORTANT", lambda text: Color.colorize_wrap(text, colorama.Back.YELLOW)],
        [r"(?:(http|ftp|https):\/\/([\w\-_]+)?(?:(?:\.[\w\-_]+)+))([\w\-\.,@?^=%&:/~\+#]*[\w\-\@?^=%&/~\+#])?", lambda text: Color.colorize_wrap(text, colorama.Fore.BLUE)],
        [r"PENDING", lambda text: Color.colorize_wrap(text, colorama.Back.BLACK + colorama.Fore.WHITE)],
        [r"LOW.*[\n\r]", lambda text: Color.colorize_wrap(text, colorama.Fore.LIGHTBLACK_EX)],
        [r"\*\*\w+\*\*", lambda text: Color.colorize_wrap(text, colorama.Style.BRIGHT)],
    ]

    @staticmethod
    def _chunk_append(chunks, text, pos_last, pos_from, pos_to, formatter):
        chunk_before = text[pos_last:pos_from]
        chunk_range = formatter(text[pos_from : pos_to])
        chunks += [chunk_before, chunk_range]

        return chunks

    @staticmethod
    def colorize_bold(s):
        return Color.colorize_wrap(s, colorama.Style.BRIGHT)

    @staticmethod
    def colorize(text: str, rules=RULES, re_flags=0):
        for rule, formatter in rules:
            chunks = []
            pos_last = 0

            for m in re.finditer(rule, text, flags=re_flags):
                chunks = Color._chunk_append(chunks, text, pos_last, *m.span(0), formatter)
                pos_last = m.span(0)[1]

            if 0 < pos_last:
                chunks.append(text[pos_last:])
                text = "".join(chunks)

        return text


class TextFormat:

    @staticmethod
    def task_format(q, task, formatters):
        ret = task

        for fmt in formatters:
            ret = fmt(ret, **q.task_info(task))

            if ret is None:
                return None

        return ret

    @staticmethod
    def _queue_format(q, formatters_todo, formatters_done=None):
        formatted = ["TODO:"]
        formatted += list(map(lambda t: TextFormat.task_format(q, t, formatters_todo), q.todo_tasks()))

        if formatters_done is not None:
            formatted += ["DONE:"]
            formatted += list(map(lambda t: TextFormat.task_format(q, t, formatters_done), q.done_tasks()))

        formatted = list(filter(lambda t: t is not None, formatted))
        formatted = "\n".join(formatted)

        return formatted

    @staticmethod
    def queue_format_complete(q):
        formatters_todo = [
            lambda t, *args, **kwargs: TextFormat.task_format_filter_default(t, *args, **kwargs, istodo=True),
            lambda t, *args, **kwargs: Color.colorize(t)
        ]
        formatters_done = [
            lambda t, *args, **kwargs: TextFormat.task_format_filter_default(t, *args, **kwargs, istodo=False)
        ]

        return TextFormat._queue_format(q, formatters_todo, formatters_done)

    @staticmethod
    def queue_format_short(q):
        formatters_todo = [
            lambda t, *args, **kwargs: TextFormat.task_format_filter_short(t, *args, **kwargs, istodo=True),
            lambda t, *args, **kwargs: Color.colorize(t)
        ]
        formatters_done = [
            lambda t, *args, **kwargs: TextFormat.task_format_filter_short(t, *args, **kwargs, istodo=False)
        ]

        return TextFormat._queue_format(q, formatters_todo, formatters_done)

    @staticmethod
    def task_format_complete_search_and(queue, queries, match_case):
        if match_case:
            adjust_case = lambda x: x
        else:
            adjust_case = lambda x: x.lower()

        def colorize_search_highlight(text):
            for q in queries:
                text = Color.colorize(text, [[q, lambda t: Color.colorize_wrap(t, *Color.SEARCH_HIGHLIGHT)]], 0 if match_case else re.IGNORECASE)

            return text

        formatters_todo = [
            lambda t, *args, **kwargs: t if all(map(lambda q: adjust_case(q) in adjust_case(t), queries)) else None,  # Search for entries that satisfy the query
            lambda t, *args, **kwargs: TextFormat.task_format_filter_default(t, *args, **kwargs, istodo=True),
            lambda t, *args, **kwargs: Color.colorize(t),
            lambda t, *args, **kwargs: Color.colorize(t, [[r'\w+', colorize_search_highlight]]),
        ]

        return TextFormat._queue_format(queue, formatters_todo)

    __DEFAULT_MULTILINE_SPLITTER = None

    @staticmethod
    def default_multiline_splitter():
        """
        Gets currently used default multiline splitter. Always returns a valid
        value.
        """

        if TextFormat.__DEFAULT_MULTILINE_SPLITTER is None:
            return '\n'
        else:
            return TextFormat.__DEFAULT_MULTILINE_SPLITTER

    @staticmethod
    def get_multiline_splitter(s):
        """
        Tries to infer line splitting format by the provided string.
        As a side effect, sets a global variable `__DEFAULT_MULTILINE_SPLITTER`
        """
        if re.search(r'\r\n', s) is not None:
            ret = r'\r\n'
            TextFormat.__DEFAULT_MULTILINE_SPLITTER = '\r\n'
        else:
            ret = r'\n'
            TextFormat.__DEFAULT_MULTILINE_SPLITTER = '\n'

        return ret

    @staticmethod
    def split_multiline(s):
        assert len(s) > 0
        return re.split(TextFormat.get_multiline_splitter(s), s, flags=re.MULTILINE)

    @staticmethod
    def split_double_multiline(s):
        assert len(s) > 0
        ret = re.split(r'(?:' + TextFormat.get_multiline_splitter(s) +
                          r'){2,}', s, flags=re.MULTILINE)
        ret = list(filter(lambda s: len(s) != 0, ret))

        return ret

    @staticmethod
    def split_first_line(s):
        assert len(s) > 0
        s = re.split(TextFormat.get_multiline_splitter(s), s, maxsplit=1, flags=re.MULTILINE)

        if len(s) == 1:
            s += [""]

        return s

    @staticmethod
    def splitlines(s):
        assert len(s) > 0
        return re.split(TextFormat.get_multiline_splitter(s), s, flags=re.MULTILINE)

    @staticmethod
    def task_format_filter_default(task, *args, **kwargs):
        due = kwargs.pop("due", None)
        details = kwargs.pop("details", "")
        header = kwargs.pop("header")
        header_col_width = 30

        if kwargs.pop("istodo"):
            marker = Color.colorize_bold(" +")
        else:
            marker = " ✓"

        if len(details) > 0:
            header = Color.colorize_bold(header)

        if due is not None:
            header = "(%s) %s" % (DateTime.deadline_format_remaining(due), header)

        details = textwrap.indent(details, ' ')
        header = header + '\n' + details

        formatted = [[marker, header]]
        ret = tabulate.tabulate(formatted, tablefmt="plain", maxcolwidths=[None, None],
            colalign=(None, None))

        return ret

    @staticmethod
    def task_format_filter_short(task, *args, **kwargs):
        header = kwargs.pop("header")
        due = kwargs.pop("due", None)
        marker_more = "..." if len(kwargs.pop("details", "")) > 0 else ""

        if due is not None:
            header = "(%s) %s" % (DateTime.deadline_format_remaining(due), header)

        if kwargs.pop("istodo"):
            marker = Color.colorize_bold(" +")
        else:
            marker = " ✓ "

        return "%s %s %s" % (marker, header, Color.colorize_bold(marker_more))


class DateTime:
    @staticmethod
    def get_datetime():
        return CURRENT_TIME

    @staticmethod
    def parse_datetime(task):
        date, status = deadline = Calendar().parse(task)
        # deadline = datetime.datetime.strftime(deadline, TIME_FORMAT)

        if status:
            return datetime.datetime(*date[:6])

    @staticmethod
    def deadline_format_remaining(deadline: str):
        delta = date_parse(deadline) - datetime.datetime.now()
        expired = delta.total_seconds() < 0
        delta = datetime.timedelta(seconds=abs(delta.total_seconds()))
        resoultion_mapping = [
            (datetime.timedelta(weeks=9), lambda d: "%d months" % int(d.days / 30)),
            (datetime.timedelta(weeks=2), lambda d: "%d weeks" % int(d.days / 7)),
            (datetime.timedelta(days=2), lambda d: "%d days" % int(d.days)),
            (datetime.timedelta(hours=2), lambda d: "%d hours" % int(d.total_seconds() / 3600)),
            (datetime.timedelta(seconds=-1), lambda d: "%d minutes" % int(d.total_seconds() /  60)),
        ]
        formatted = ""

        for threshold, formatter in resoultion_mapping:
            if delta > threshold:
                formatted = formatter(delta)
                break

        if expired:
            formatted = "%s late" % formatted
        else:
            formatted = "in %s" % formatted

        return formatted


@dataclass
class Queue:
    QUEUE_FILE = str(Path(os.path.dirname(os.path.realpath(__file__))).resolve() / "todo.json")
    tasks: dict
    queue_dir: str = None
    dump: bool = False  # A flag which defines whether a backup will be saved.

    # TODO: backup restore

    @staticmethod
    def load(from_here=False):
        if not from_here:
            queue_file = Queue.QUEUE_FILE
        else:
            queue_file = str(Path(".").resolve() / "todo.json")

        try:
            with open(queue_file, 'r') as f:
                queue_dir = os.path.dirname(queue_file)
                q = Queue(json.loads(f.read()), queue_dir=queue_dir)

                if "version" not in q.tasks.keys():
                    q._sync_task_info(force_update=True)
                elif q.tasks["version"] != VERSION:
                    q._sync_task_info(force_update=True)

                return q
        except Exception as e:
            Log.error(Queue, f"got exception", str(e))
            return Queue({
                "todo": [],
                "done": [],
                "info": dict(),
            })

    def task_info(self, task):
        """
        Returns a `dict` object w/ the following fields
        - "header"
        - "details" (optional)
        - "due" (optional)
        """
        return self.tasks["info"][task]

    def todo_tasks(self):
        return self.tasks["todo"]

    def done_tasks(self):
        return self.tasks["done"]

    def _task_get_deadline(self, task):
        if task not in self.tasks["info"]:
            return None

        if "due" not in self.tasks["info"][task]:
            return None

        return self.tasks["info"][task]["due"]

    def _sort(self):
        self.todo_tasks().sort()

        # Partition the list of tasks based on whether a task has a deadline
        tasks_deadline = list(filter(lambda t: self._task_get_deadline(t) is not None, self.todo_tasks()))
        tasks_no_deadline = list(filter(lambda t: t not in tasks_deadline, self.todo_tasks()))
        tasks_deadline.sort(key=lambda t: date_parse(self._task_get_deadline(t)))
        self.tasks["todo"] = tasks_deadline + tasks_no_deadline

    def save(self, here=False):
        self._sort()

        if not here:
            queue_file = Queue.QUEUE_FILE
        else:
            queue_file = str(Path(".") / "todo.json")

        with open(queue_file, 'w') as f:
            f.write(json.dumps(self.tasks, indent=4))

        if self.dump:
            try:
                os.mkdir(Path(self.queue_dir) / ".tododump")
            except Exception:
                pass

            dump_file_path = str((Path(self.queue_dir) / ".tododump" \
                / DUMP_DURRENT_TIME).resolve()) \
                + ".json.gz"
            with open(dump_file_path, "wb+") as f:
                output = json.dumps(self.tasks, indent=4)
                output = output.encode("raw_unicode_escape")
                output = gzip.compress(output)
                f.write(output)

    @staticmethod
    def _task_parse_info(task):
        ret = dict()

        Log.debug("parsing info for task", task)
        deadline = None

        for d in map(lambda d: DateTime.parse_datetime(d), TextFormat.split_multiline(task)):
            if d is not None:
                if deadline is None:
                    deadline = d
                elif d < deadline:
                    deadline = d

        if deadline:
            ret["due"] = datetime.datetime.strftime(deadline, TIME_FORMAT)

        details = TextFormat.split_first_line(task)
        ret["header"] = details[0]
        ret["details"] = ""

        if len(details) == 2:
            ret["details"] = details[1]

        return ret

    def search_and(self, queries, match_case, category="todo"):
        assert category in ["todo", "done"]
        if match_case:
            adjust_case = lambda x: x
        else:
            adjust_case = lambda x: x.lower()

        queries_check = lambda t: all(map(lambda q: adjust_case(q) in adjust_case(t), queries))
        map_search_match = map(lambda t: t if queries_check(t) else None, self.tasks[category])
        map_search_filter = filter(lambda t: t is not None, map_search_match)

        return list(map_search_filter)

    def undo(self, item):
        self.dump = True
        list_remove_item(self.done_tasks(), item)
        self.todo_tasks().append(item)
        self._sync_task_info()

    def do(self, item):
        self.dump = True
        list_remove_item(self.todo_tasks(), item)
        self.done_tasks().append(item)
        self._sync_task_info()

    def _sync_task_info(self, force_update=False):
        stall_info = []
        self.tasks["version"] = VERSION

        for k in self.tasks["info"].keys():
            if k not in self.todo_tasks() and k not in self.done_tasks():
                stall_info += [k]

        for si in stall_info:
            self.tasks["info"].pop(si)

        for category in ["todo", "done"]:
            for t in self.tasks[category]:
                if t not in self.tasks["info"].keys() or force_update:
                    self.tasks["info"][t] = Queue._task_parse_info(t)

    def add(self, task):
        """
        Ensures cohesion b/w `self.todo` and `self.task_info`
        """
        self.dump = True
        self.tasks["todo"] += [task]
        self._sync_task_info()

    def item_edit(self, items_before, items_after):
        """
        Edit/Split item
        """
        self.dump = True
        for item in items_before:
            list_remove_item(self.todo_tasks(), item)

        self.todo_tasks().extend(list(items_after))
        self._sync_task_info()

    def clear_done(self):
        self.dump = True
        self.tasks["done"] = []


class PlainTextQueue(Queue):
    QUEUE_FILE = str(Path(os.path.dirname(os.path.realpath(__file__))).resolve() / "todo.txt")
    _DONE_MARKER = "@done"
    _DUE_MARKER = "@due"

    @staticmethod
    def load(from_here=False):
        # Select working directory
        if not from_here:
            queue_file = PlainTextQueue.QUEUE_FILE
        else:
            queue_file = str(Path(".").resolve() / "todo.txt")

        queue_dir = os.path.dirname(queue_file)

        try:
            with open(queue_file, 'r') as f:
                tasks = dict()  # Backward-compatible dict-based data structure
                tasks["done"] = []
                tasks["todo"] = []
                tasks["info"] = dict()
                all_tasks = TextFormat.split_double_multiline(f.read())
                all_tasks = list(map(lambda s: s.strip(), all_tasks))

                Log.debug("all_tasks", all_tasks)
                # Separate b/w "todo" and "done" tasks
                for task in all_tasks:
                    if PlainTextQueue._DONE_MARKER in task:
                        tasks["done"].append(task)
                    else:
                        tasks["todo"].append(task)

                    tasks["info"][task] = PlainTextQueue._task_parse_info(task)

                ret = PlainTextQueue(tasks=tasks, queue_dir=queue_dir)
                ret._sync_task_info(force_update=True)

                return ret

        except Exception as e:
            Log.error(PlainTextQueue, "got exception", str(e))

            return PlainTextQueue(
                tasks={
                    "todo": [],
                    "done": [],
                    "info": dict(),
                },
                queue_dir=queue_dir
            )

    def _sync_task_info(self, force_update=False):
        stall_info = []
        self.tasks["version"] = VERSION

        for k in self.tasks["info"].keys():
            if k not in self.todo_tasks() and k not in self.done_tasks():
                stall_info += [k]

        for si in stall_info:
            self.tasks["info"].pop(si)

        for category in ["todo", "done"]:
            for t in self.tasks[category]:
                if t not in self.tasks["info"].keys() or force_update:
                    self.tasks["info"][t] = PlainTextQueue._task_parse_info(t)

    def _serialized_task_info(self, task):
        """
        Produces a serialized metainfo for a task
        """
        lines = []
        lines.append(self.tasks["info"][task]["header"])
        lines.append(self.tasks["info"][task]["details"])
        due = _dict_try_get_value(self.tasks["info"][task], "due")

        if due is not None:
            lines.append("@due " + str(due))

        if task in self.tasks["done"]:
            lines.append("@done")

        lines = list(filter(lambda s: len(s), lines))

        return TextFormat.default_multiline_splitter().join(lines)

    def _as_serialized(self):
        """
        Converts the internal data structure into a restorable portable text
        format
        """
        ret = self.todo_tasks() + self.done_tasks()
        ret = list(map(self._serialized_task_info, ret))
        multiline_splitter = TextFormat.default_multiline_splitter() * 2
        ret = multiline_splitter.join(ret)

        return ret

    @staticmethod
    def _task_parse_details(task):
        def is_metaline(metaline_candidate):
            return PlainTextQueue._DUE_MARKER in metaline_candidate \
                or PlainTextQueue._DONE_MARKER in metaline_candidate

        ret = dict()
        details = TextFormat.split_first_line(task)
        ret["header"] = details[0]
        ret["details"] = ""

        if len(details) == 2 and len(details[1]) > 0:
            # Strip off metainfo

            ret["details"] = TextFormat.default_multiline_splitter().join(
                filter(
                    lambda l: not is_metaline(l),
                    TextFormat.split_multiline(details[1])
                )
            )

        return ret

    @staticmethod
    def _task_parse_due_date(task):
        """
        Extracts due date from a text string
        """
        ret = dict()
        deadline = None

        for line in TextFormat.split_multiline(task):
            deadline_candidate = DateTime.parse_datetime(line)

            if line.startswith(PlainTextQueue._DUE_MARKER):
                break

            if deadline_candidate is not None:
                if deadline is None:
                    deadline = deadline_candidate
                elif deadline_candidate < deadline:
                    deadline = deadline_candidate

        if deadline is not None:
            ret["due"] = datetime.datetime.strftime(deadline, TIME_FORMAT)

        return ret

    @staticmethod
    def _task_parse_info(task):
        details = PlainTextQueue._task_parse_details(task)
        due = PlainTextQueue._task_parse_due_date(task)

        return dict(
            **details,
            **due
        )

    def save(self, here=False):
        self._sort()

        if not here:
            queue_file = PlainTextQueue.QUEUE_FILE
        else:
            queue_file = str(Path(".") / "todo.txt")

        serialized = self._as_serialized()

        with open(queue_file, 'w') as f:
            f.write(serialized)

        # Create a gzipped backup
        if self.dump:
            try:
                os.mkdir(Path(self.queue_dir) / ".tododump")
            except Exception:
                pass

            dump_file_path = str((Path(self.queue_dir) / ".tododump" \
                / DUMP_DURRENT_TIME).resolve()) \
                + ".txt.gz"

            with open(dump_file_path, "wb+") as f:
                output = serialized
                output = output.encode("raw_unicode_escape")
                output = gzip.compress(output)
                f.write(output)


class Cli:
    TEXT_EDITOR = "vim"

    @staticmethod
    def list_select(items, title):

        if len(items) == 0:
            return None
        elif len(items) == 1:
            return items[0]

        items_short = list(map(lambda i: TextFormat.split_first_line(i)[0], items))
        item_id = TerminalMenu(items_short, title=title).show()

        if item_id is None:
            return None

        item = items[item_id]

        return item

    @staticmethod
    def list_select_multi(items, title):
        if len(items) == 0:
            return []
        elif len(items) == 1:
            return [items[0]]

        items_short = list(map(lambda i: TextFormat.split_first_line(i)[0], items))
        item_ids = TerminalMenu(items_short, title=title, multi_select=True).show()

        if item_ids is None:
            return []

        selected = [items[i] for i in item_ids]

        return selected

    def yn(title):
        return bool(TerminalMenu(['[n] No', '[y] Yes'], title=title).show())

    def print_help():
        entries = [
            ["?", "Show this help message"],
            ["NONE", "Show list of tasks"],
            ["f ..", "Filter tasks"],
            ["F ..", "Filter tasks (case-sensitive)"],
            ["h ..", "Use  JSON from the current directory"],
            ["a ..", "Add"],
            ["e", "Edit in an external terminal editor \n(vim by default, tweak the source \nfile to replace)"],
            ["e ..", "Filter-edit"],
            ["ae...", "Search for an already existing task using the keywords provided.\nIf none was found, add and open for edit"],
            ["E ..", "Filter-edit (case-sensitive)"],
            ["d", "Do. Mark tasks as done"],
            ["d..", "Filter-do"],
            ["D..", "Filter-do (case-sensitive)"],
            ["u", "Undo. Mark tasks as undone"],
            ["u..", "Filter-undo"],
            ["U..", "Filter-undo (case-sensitive)"],
            ["cd", "Clear DONE backlog"],
            ["m", "More. Show details"],
        ]
        entries = list(map(lambda i: [Color.colorize_wrap(i[0], *Color.HELP_ENTRY), i[1]], entries))
        print(tabulate.tabulate(entries, tablefmt="plain", colalign=["left", "left"]))

    def _item_edit_external_editor(items):
        with open(".todotempedit", 'w') as f:
            f.write('\n\n'.join(items))

        os.system(Cli.TEXT_EDITOR + ' ' + ".todotempedit")

        with open(".todotempedit") as f:
            new_items = TextFormat.split_double_multiline(f.read())
            new_items = list(map(str.strip, new_items))
            new_items = list(filter(lambda s: len(s) > 0, new_items))

        os.remove(".todotempedit")

        return new_items

    def list_edit(lst, title):
        item = Cli.list_select(lst, title=title)

        if item is None:
            return None, None

        new_items = Cli._item_edit_external_editor([item])

        return item, new_items

    def list_edit_multi(lst, title):
        items = Cli.list_select_multi(lst, title=title)

        if len(items) == 0:
            return None, None

        new_items = Cli._item_edit_external_editor(items)

        return items, new_items

    @staticmethod
    def queue_add(q, task):
        task = ' '.join(task)
        task = task.strip()

        if len(task):
            q.add(task)

    @staticmethod
    def queue_search(q, case_sensitive):
        item, items = Cli.list_edit_multi(q.search_and(sys.argv[2:], case_sensitive), "Select items to edit")

        if item is not None:
            q.item_edit(item, items)

            return True

        return False


def main():
    if len(sys.argv) > 1:
        from_here = 'h' == sys.argv[1].strip()

        if from_here:
            sys.argv = sys.argv[:1] + sys.argv[2:]
    else:
        from_here = False

    q = PlainTextQueue.load(from_here)

    if len(sys.argv) >= 3:
        if sys.argv[1] == 'a':  # add
            Cli.queue_add(q, sys.argv[2:])
        elif sys.argv[1] == 'f':  # filter
            print(TextFormat.task_format_complete_search_and(q, sys.argv[2:], False))
        elif sys.argv[1] == 'F':
            print(TextFormat.task_format_complete_search_and(q, sys.argv[2:], True))
        elif sys.argv[1] == 'e':
            Cli.queue_search(q, False)
        elif sys.argv[1] == 'E':
            Cli.queue_search(q, True)
        elif sys.argv[1] == 'u':  # Filter-undo
            for item in Cli.list_select_multi(q.search_and(sys.argv[2:], False, "done"), "Undo:"):
                q.undo(item)
        elif sys.argv[1] == 'U':  # Case-sensitive filter-undo
            for item in Cli.list_select_multi(q.search_and(sys.argv[2:], True, "done"), "Undo:"):
                q.undo(item)
        elif sys.argv[1] == 'd':  # Filter-do
            for item in Cli.list_select_multi(q.search_and(sys.argv[2:], False), "Done: "):
                q.do(item)
        elif sys.argv[1] == 'D':  # Case-sensitive filter-do
            for item in Cli.list_select_multi(q.search_and(sys.argv[2:], True), "Done: "):
                q.do(item)
        elif sys.argv[1].lower() == "ae":
            if not Cli.queue_search(q, False):
                Cli.queue_add(q, sys.argv[2:])
                Cli.queue_search(q, True)
    elif len(sys.argv) == 2:
        if sys.argv[1] == 'u':  # undo
            for item in Cli.list_select_multi(q.done_tasks(), "Undo:"):
                q.undo(item)
        elif sys.argv[1] == 'd':  # do
            for item in Cli.list_select_multi(q.todo_tasks(), "Done: "):
                q.do(item)
        elif sys.argv[1] == "cd":  # clear done
            if Cli.yn('Clear "DONE"?'):
                q.clear_done()
        elif sys.argv[1] == 'e':
            item, items = Cli.list_edit_multi(q.todo_tasks(), "Select items to edit")

            if item is not None:
                q.item_edit(item, items)
        elif sys.argv[1] == 'm':  # more
            print(TextFormat.queue_format_complete(q))
        elif sys.argv[1] == "?":
            Cli.print_help()
    elif len(sys.argv) == 1:
        print(TextFormat.queue_format_short(q))

    q.save(from_here)


if __name__ == "__main__":
    main()
