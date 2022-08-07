#!/usr/bin/python3
# -*- coding: UTF-8 -*-

import sys
import os
from tkinter import W
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


TIME_FORMAT = "%Y-%m-%d %H:%M"
CURRENT_TIME = datetime.datetime.strftime(datetime.datetime.now(), TIME_FORMAT)
tabulate.PRESERVE_WHITESPACE = True


def list_remove_item(l, item):
    try:
        l.remove(item)
    except ValueError:
        pass


class Color:

    @staticmethod
    def _colorize_impl(text, *colors):
        return "".join(colors) + text + colorama.Style.RESET_ALL

    # This set of rules may be extended w/ any formatting code whatsoever
    RULES = [
        [r"IMPORTANT", lambda text: Color._colorize_impl(text, colorama.Back.YELLOW)],
        [r"(?:(http|ftp|https):\/\/([\w\-_]+)?(?:(?:\.[\w\-_]+)+))([\w\-\.,@?^=%&:/~\+#]*[\w\-\@?^=%&/~\+#])?", lambda text: Color._colorize_impl(text, colorama.Fore.BLUE)]
    ]

    @staticmethod
    def _chunk_append(chunks, text, pos_last, pos_from, pos_to, formatter):
        chunk_before = text[pos_last:pos_from]
        chunk_range = formatter(text[pos_from : pos_to])
        chunks += [chunk_before, chunk_range]

        return chunks

    @staticmethod
    def colorize(text: str):
        for rule, formatter in Color.RULES:
            chunks = []
            pos_last = 0

            for m in re.finditer(rule, text):
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
            ret = fmt(ret, **q.tasks["info"][task])

            if ret is None:
                return None

        return ret

    @staticmethod
    def _format(q, formatters_todo, formatters_done=None):
        formatted = ["TODO:"]
        formatted += list(map(lambda t: TextFormat.task_format(q, t, formatters_todo), q.tasks["todo"]))

        if formatters_done is not None:
            formatted += ["DONE:"]
            formatted += list(map(lambda t: TextFormat.task_format(q, formatters_done), q.tasks["done"]))

        formatted = list(filter(lambda t: t is not None, formatted))
        formatted = "\n".join(formatted)

        return formatted

    @staticmethod
    def format_complete(q):
        formatters_todo = [
            lambda t, *args, **kwargs: TextFormat.task_format_filter_default(t, *args, **kwargs, istodo=True),
            lambda t, *args, **kwargs: Color.colorize(t)
        ]
        formatters_done = [
            lambda t, *args, **kwargs: TextFormat.task_format_filter_default(t, *args, **kwargs, istodo=False)
        ]

        return TextFormat._format(q, formatters_todo, formatters_done)

    @staticmethod
    def format_short(q):
        formatters_todo = [
            lambda t, *args, **kwargs: TextFormat.task_format_filter_short(t, *args, **kwargs, istodo=True),
            lambda t, *args, **kwargs: Color.colorize(t)
        ]
        formatters_done = [
            lambda t, *args, **kwargs: TextFormat.task_format_filter_short(t, *args, **kwargs, istodo=False)
        ]

        return TextFormat._format(q, formatters_todo, formatters_done)

    @staticmethod
    def task_format_complete_search_and(queue, queries, match_case):
        if match_case:
            adjust_case = lambda x: x
        else:
            adjust_case = lambda x: x.lower()

        formatters_todo = [
            lambda t, *args, **kwargs: t if all(map(lambda q: adjust_case(q) in adjust_case(t), queries)) else None,  # Search for entries that satisfy the query
            lambda t, *args, **kwargs: TextFormat.task_format_filter_default(t, *args, **kwargs, istodo=True),
            lambda t, *args, **kwargs: Color.colorize(t)
        ]

        return TextFormat._format(q, formatters_todo)

    @staticmethod
    def get_multiline_splitter(s):
        if re.search(r'\r\n', s) is not None:
            return r'\r\n'

        return r'\n'

    @staticmethod
    def split_double_multiline(s):
        assert len(s) > 0
        return re.split(TextFormat.get_multiline_splitter(s) * 2, s, flags=re.MULTILINE)

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
            marker = " + "
        else:
            marker = " ✓ "

        if due is not None:
            header = "(%s)\n%s" % (DateTime.deadline_format_remaining(due), header)

        formatted = [marker, header, details]
        formatted = [["", "." * header_col_width, ""]] + [formatted]  # Hack: artificially extend the length of the header
        ret = tabulate.tabulate(formatted, tablefmt="plain", maxcolwidths=[None, header_col_width, None])
        ret = TextFormat.split_first_line(ret)[1]  # Remove the artificial row

        return ret

    @staticmethod
    def task_format_filter_short(task, *args, **kwargs):
        header = kwargs.pop("header")
        due = kwargs.pop("due", None)

        if due is not None:
            header = "(%s) %s" % (DateTime.deadline_format_remaining(due), header)

        if kwargs.pop("istodo"):
            marker = " + "
        else:
            marker = " ✓ "

        return "%s %s" % (marker, header)


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
            (datetime.timedelta(weeks=8), lambda d: "%d months" % int(d.days / 30)),
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
    QUEUE_FILE = str(Path(os.path.dirname(os.path.realpath(__file__))) / "todo.json")

    tasks: dict

    @staticmethod
    def load(from_here=False):
        if not from_here:
            queue_file = Queue.QUEUE_FILE
        else:
            queue_file = str(Path(".") / "todo.json")

        try:
            with open(queue_file, 'r') as f:
                return Queue(json.loads(f.read()))
        except:
            return Queue({
                "todo": [],
                "done": [],
                "info": dict(),
            })

    def _task_get_deadline(self, task):
        if task not in self.tasks["info"]:
            return None

        if "due" not in self.tasks["info"][task]:
            return None

        return self.tasks["info"][task]["due"]

    def sort(self):
        self.tasks["todo"].sort()

        # Partition the list of tasks based on whether a task has a deadline
        tasks_deadline = list(filter(lambda t: self._task_get_deadline(t) is not None, self.tasks["todo"]))
        tasks_no_deadline = list(filter(lambda t: t not in tasks_deadline, self.tasks["todo"]))
        tasks_deadline.sort(key=lambda t: date_parse(self._task_get_deadline(t)))
        self.tasks["todo"] = tasks_deadline + tasks_no_deadline

    def save(self, here=False):
        self.sort()

        if not here:
            queue_file = Queue.QUEUE_FILE
        else:
            queue_file = str(Path(".") / "todo.json")

        with open(queue_file, 'w') as f:
            f.write(json.dumps(self.tasks, indent=4))

    @staticmethod
    def _task_parse_info(task):
        ret = dict()
        deadline = DateTime.parse_datetime(task)

        if deadline:
            ret["due"] = datetime.datetime.strftime(deadline, TIME_FORMAT)

        details = TextFormat.split_first_line(task)
        ret["header"] = details[0]
        ret["details"] = ""

        if len(details) == 2:
            ret["details"] = details[1]

        return ret

    def task_get_info(self, task, infokey):
        if task not in self.tasks["todo"] and task not in self.tasks["done"]:
            return None

        assert task in self.tasks["info"]

        if infokey not in self.tasks["info"][task]:
            return None

        return self.tasks["info"][task][infokey]

    def __str__(self):
        formatter_default_todo = lambda t, *args, **kwargs: TextFormat.task_format_filter_default(t, *args, **kwargs, istodo=True)
        formatter_default_done = lambda t, *args, **kwargs: TextFormat.task_format_filter_default(t, *args, **kwargs, istodo=False)
        formatter_colorize = lambda t, *args, **kwargs: Color.colorize(t)
        formatted = ["TODO:"]
        formatted += list(map(lambda t: self.task_format(t, [formatter_default_todo, formatter_colorize]), self.tasks["todo"]))
        formatted += ["DONE:"]
        formatted += list(map(lambda t: self.task_format(t, [formatter_default_done]), self.tasks["done"]))
        formatted = list(filter(lambda t: t is not None, formatted))
        formatted = "\n".join(formatted)

        return formatted

    def undo(self, item):
        list_remove_item(self.tasks["done"], item)
        self.tasks["todo"].append(item)
        self._sync_task_info()

    def do(self, item):
        list_remove_item(self.tasks["todo"], item)
        self.tasks["done"].append(item)
        self._sync_task_info()

    def _sync_task_info(self):
        stall_info = []

        for k in self.tasks["info"].keys():
            if k not in self.tasks["todo"] and k not in self.tasks["done"]:
                stall_info += [k]

        for si in stall_info:
            self.tasks["info"].pop(si)

        for category in ["todo", "done"]:
            for t in self.tasks[category]:
                if t not in self.tasks["info"].keys():
                    self.tasks["info"][t] = Queue._task_parse_info(t)

    def add(self, task):
        """
        Ensures cohesion b/w `self.todo` and `self.task_info`
        """
        self.tasks["todo"] += [task]
        self._sync_task_info()

    def item_edit(self, item, *items):
        """
        Edit/Split item
        """
        list_remove_item(self.tasks["todo"], item)
        self.tasks["todo"].extend(list(items))
        self._sync_task_info()

    def get_done(self):
        return self.tasks["done"]

    def get_todo(self):
        return self.tasks["todo"]

    def clear_done(self):
        self.tasks["done"] = []

class Cli:
    TEXT_EDITOR = "vim"

    @staticmethod
    def list_select(items, title):
        items_short = list(map(lambda i: TextFormat.split_first_line(i)[0], items))
        item_id = TerminalMenu(items_short, title=title).show()

        if item_id is None:
            return None

        item = items[item_id]

        return item

    @staticmethod
    def list_select_multi(items, title):
        items_short = list(map(lambda i: TextFormat.split_first_line(i)[0], items))
        item_ids = TerminalMenu(items_short, title=title, multi_select=True).show()

        if item_ids is None:
            return []

        selected = [items[i] for i in item_ids]

        return selected

    def yn(title):
        return bool(TerminalMenu(['[n] No', '[y] Yes'], title=title).show())

    def print_help():
        print(tabulate.tabulate([
            ["?", "Show this help message"],
            ["NONE", "Show list of tasks"],
            ["f ..", "Filter tasks (case-insensitive)"],
            ["F ..", "Filter tasks (case-sensitive)"],
            ["h ..", "Use  JSON from the current directory"],
            ["a ..", "Add"],
            ["e", "Edit in an external terminal editor \n(vim by default, tweak the source \nfile to replace)"],
            ["d", "Do. Mark tasks as done"],
            ["u", "Undo. Mark tasks as undone"],
            ["cd", "Clear DONE backlog"],
            ], tablefmt="fancy_grid"))

    def list_edit(lst, title):
        item = Cli.list_select(lst, title=title)

        if item is None:
            return None, None

        with open(".todotempedit", 'w') as f:
            f.write(item)

        os.system(Cli.TEXT_EDITOR + ' ' + ".todotempedit")

        with open(".todotempedit") as f:
            new_items = TextFormat.split_double_multiline(f.read())
            new_items = list(map(str.strip, new_items))
            new_items = list(filter(lambda s: len(s) > 0, new_items))

        os.remove(".todotempedit")

        return item, new_items


def main():
    if len(sys.argv) > 1:
        from_here = 'h' == sys.argv[1].strip()

        if from_here:
            sys.argv = sys.argv[:1] + sys.argv[2:]
    else:
        from_here = False

    q = Queue.load(from_here)

    if len(sys.argv) >= 3:
        if sys.argv[1] == 'a':  # add
            task = sys.argv[2:]
            task = ' '.join(task)
            task = task.strip()
            if len(task):
                q.add(task)
        elif sys.argv[1].lower() == 'f':  # filter
            case_cb = lambda f: f if sys.argv[1].isupper() else f.lower()
            out = str(q)
            out = out.split('\n')
            out = [o for o in out if case_cb(sys.argv[2]) in case_cb(o)]
            print('\n'.join(out))
    elif len(sys.argv) == 2:
        if sys.argv[1] == 'u':  # undo
            for item in Cli.list_select_multi(q.get_done(), "Undo:"):
                q.undo(item)
        elif sys.argv[1] == 'd':  # do
            for item in Cli.list_select_multi(q.get_todo(), "Done: "):
                q.do(item)
        elif sys.argv[1] == "cd":  # clear done
            if Cli.yn('Clear "DONE"?'):
                q.clear_done()
        elif sys.argv[1] == 'e':
            item, items = Cli.list_edit(q.get_todo(), "Select an item to edit")

            if item is not None:
                q.item_edit(item, *items)
        elif sys.argv[1] == "?":
            Cli.print_help()
    elif len(sys.argv) == 1:
        print(TextFormat.format_complete(q))

    q.save(from_here)


if __name__ == "__main__":
    main()
