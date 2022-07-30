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


TIME_FORMAT = "%Y-%m-%d %H:%M"
CURRENT_TIME = datetime.datetime.strftime(datetime.datetime.now(), TIME_FORMAT)


def list_remove_item(l, item):
    try:
        l.remove(item)
    except ValueError:
        pass


class Color:

    RULES = [
        [r"IMPORTANT", colorama.Back.YELLOW],
        [r"LONGTERM", colorama.Fore.BLUE],
        [r"(http|ftp|https):\/\/([\w\-_]+(?:(?:\.[\w\-_]+)+))([\w\-\.,@?^=%&:/~\+#]*[\w\-\@?^=%&/~\+#])?", colorama.Fore.BLUE]
    ]

    @staticmethod
    def _chunk_append(chunks, text, pos_last, pos_from, pos_to, *colors):
        chunk_before = text[:pos_from]
        chunk_range = "".join(colors) + text[pos_from : pos_to] + colorama.Style.RESET_ALL
        chunk_after = text[pos_to:]
        chunks += [chunk_before, chunk_range, chunk_after]

        return chunks

    @staticmethod
    def colorize(text: str):
        print(text)
        for rule, *colors in Color.RULES:
            chunks = []
            pos_last = 0

            for m in re.finditer(rule, text):
                chunks = Color._chunk_append(chunks, text, pos_last, *m.span(0), *colors)
                pos_last = m.span(0)[1]

            if len(chunks) > 0:
                text = "".join(chunks)

        return text


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

        return ret

    def __str__(self):
        ret = ""
        ret += "TODO:\n"

        for i in self.tasks["todo"]:

            deadline = self._task_get_deadline(i)
            if deadline is not None:
                deadline = "(%s) " % DateTime.deadline_format_remaining(deadline)
            else:
                deadline = ""

            ret += " + %s%s" % (deadline, i)
            info = self.tasks["info"][i]

            for k, v in info.items():
                ret += " | " + str(k) + ": " + str(v)

            ret += '\n'

        ret += "DONE:\n"

        for i in self.tasks["done"]:
            ret += " ✓ " + i + '\n'

        # Colorize
        lines = list(map(lambda l: Color.colorize(l), re.split(r"[\r\n]+", ret)))
        ret = "\n".join(lines)

        return ret

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
            if k not in self.tasks["todo"]:
                stall_info += [k]

        for si in stall_info:
            self.tasks["info"].pop(si)

        for t in self.tasks["todo"]:
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
        item_id = TerminalMenu(items, title=title).show()
        item = items[item_id]

        return item

    @staticmethod
    def list_select_multi(items, title):
        item_ids = TerminalMenu(items, title=title, multi_select=True).show()
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

    def list_edit(list, title):
        item = Cli.list_select(list, title=title)

        with open(".todotempedit", 'w') as f:
            f.write(item)

        os.system(Cli.TEXT_EDITOR + ' ' + ".todotempedit")

        with open(".todotempedit") as f:
            new_items = f.readlines()
            new_items = [l.strip() for l in new_items]

        os.system("rm .todotempedit")

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
            q.item_edit(item, *items)
        elif sys.argv[1] == "?":
            Cli.print_help()
    elif len(sys.argv) == 1:
        print(q)

    q.save(from_here)


if __name__ == "__main__":
    main()
