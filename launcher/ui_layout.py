"""Shared desktop spacing, button presentation and contained section titles."""
import math

GAP = 6
MARGIN = 12


class ChoiceVariable:
    """Display localized built-in choices without changing saved identities."""
    def __init__(self, tk, translate, reserved, value=''):
        self.variable = tk.StringVar()
        self.translate, self.reserved = translate, tuple(reserved)
        self.aliases = {name: name for name in reserved}
        self.set(value)

    def __str__(self):
        return str(self.variable)

    def display(self, value):
        if value in self.reserved:
            label = self.translate(value)
            self.aliases[label] = value
            return label
        return value

    def get(self):
        value = self.variable.get()
        return self.aliases.get(value, value)

    def set(self, value):
        self.variable.set(self.display(self.aliases.get(value, value)))


def ask_string(title, prompt, parent=None, initialvalue=None, language='zh'):
    """Use the launcher's button presentation for its own text-input dialogs."""
    import tkinter as tk
    from tkinter.simpledialog import Dialog

    class TextDialog(Dialog):
        def body(self, master):
            tk.Label(master, text=prompt, anchor='w', justify='left',
                     wraplength=520).pack(fill='x', pady=(0, GAP))
            self.entry = tk.Entry(master, width=40)
            self.entry.pack(fill='x')
            if initialvalue is not None:
                self.entry.insert(0, initialvalue)
                self.entry.select_range(0, 'end')
            return self.entry

        def buttonbox(self):
            self.entry.master.pack_configure(fill='x', padx=MARGIN, pady=(MARGIN, 0))
            actions = tk.Frame(self)
            actions.pack(fill='x', padx=MARGIN, pady=MARGIN)
            for text, command in ((('确定' if language == 'zh' else 'OK'), self.ok),
                                  (('取消' if language == 'zh' else 'Cancel'), self.cancel)):
                tk.Button(actions, text=text, command=command).pack(side='left')
            self.bind('<Return>', self.ok)
            self.bind('<Escape>', self.cancel)
            polish(self)

        def apply(self):
            self.result = self.entry.get()

    return TextDialog(parent, title).result


def section(tk, parent, text='', padding=8):
    """Return an outer border, an ordinary content frame and an inside title."""
    outer = tk.Frame(parent, borderwidth=1, relief='solid', padx=padding, pady=padding)
    title = tk.Label(outer, text=text, anchor='w', justify='left', padx=0, pady=0)
    title.pack(fill='x', pady=(0, GAP))
    body = tk.Frame(outer)
    body.pack(fill='both', expand=True)
    return outer, body, title


def polish(window):
    """Apply presentation only; leave commands, state and selection untouched.

    Equal packed action rows use a common requested width before expansion.
    Text wrapping follows the actual allocated label width, including DPI changes.
    """
    if not hasattr(window, 'winfo_children'):
        return
    for child in window.winfo_children():
        kind = child.winfo_class()
        if kind in ('Button', 'Menubutton'):
            child.configure(padx=8, pady=2, borderwidth=1, relief='raised')
        elif kind in ('Label', 'TLabel'):
            child.configure(anchor='w', justify='left')
            if kind == 'Label':
                child.configure(padx=0, pady=0)
            if float(str(child.cget('wraplength') or 0)) > 0 and not getattr(child, '_layout_wrap', False):
                child.bind('<Configure>', lambda event: event.widget.configure(
                    wraplength=max(1, event.width)), add='+')
                child._layout_wrap = True
        polish(child)
    packed = [child for child in window.winfo_children()
              if child.winfo_manager() == 'pack']
    if len(packed) > 1 and all(child.winfo_class() == 'Button' and
            child.pack_info().get('side') in ('left', 'right') for child in packed):
        # Keep the longest caption readable even in a content-sized dialog.
        # Width is expressed in font characters, not Unicode string length.
        width = max(int(math.ceil(int(child.tk.call('font', 'measure',
            child.cget('font'), child.cget('text'))) / max(1, int(child.tk.call(
                'font', 'measure', child.cget('font'), '0'))))) for child in packed)
        for index, child in enumerate(packed):
            child.configure(width=max(1, width))
            child.pack_configure(side='left', fill='x', expand=True,
                padx=(0 if index == 0 else GAP // 2,
                      0 if index == len(packed) - 1 else GAP // 2))
