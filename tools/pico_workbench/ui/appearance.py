"""Shared native desktop palette; no platform-specific drawing dependencies."""
import os
from tkinter import ttk

def apply_theme(window):
    font='Microsoft YaHei UI' if os.name=='nt' else 'Noto Sans CJK SC'
    window.resizable(True,True)
    def change_size(delta):
        size=max(8,min(18,getattr(window,'_ui_font_size',10)+delta));window._ui_font_size=size;s.configure('.',font=(font,size));return 'break'
    window.bind('<Control-plus>',lambda _:change_size(1))
    window.bind('<Control-equal>',lambda _:change_size(1))
    window.bind('<Control-minus>',lambda _:change_size(-1))
    window.configure(background='#f3f6fb')
    s=ttk.Style(window);s.theme_use('clam')
    s.configure('.',font=(font,10),background='#f3f6fb',foreground='#24334b')
    s.configure('TFrame',background='#f3f6fb')
    s.configure('TLabel',background='#f3f6fb')
    s.configure('Title.TLabel',font=(font,18,'bold'),foreground='#16253d')
    s.configure('Muted.TLabel',foreground='#6c7e95')
    s.configure('Card.TFrame',background='#ffffff',borderwidth=1,relief='solid')
    s.configure('Card.TLabel',background='#ffffff')
    s.configure('CardTitle.TLabel',background='#ffffff',foreground='#22334d',font=(font,12,'bold'))
    s.configure('CardMuted.TLabel',background='#ffffff',foreground='#6c7e95')
    s.configure('TButton',padding=(12,6),background='#ffffff',bordercolor='#d8e1ee',lightcolor='#ffffff',darkcolor='#d8e1ee')
    s.map('TButton',background=[('active','#eaf0ff')],foreground=[('disabled','#9caabd')])
    s.configure('Primary.TButton',background='#365fdf',foreground='#ffffff',bordercolor='#365fdf',font=(font,11,'bold'))
    s.map('Primary.TButton',background=[('active','#284cc0'),('disabled','#a8b8e4')],foreground=[('disabled','#eef2fc')])
    s.configure('TNotebook',background='#f3f6fb',borderwidth=0,tabmargins=(0,0,0,8))
    s.configure('TNotebook.Tab',padding=(18,7),background='#e7edf6',foreground='#60728b')
    s.map('TNotebook.Tab',background=[('selected','#ffffff')],foreground=[('selected','#315ad5')])
    s.configure('TCombobox',padding=4,fieldbackground='#ffffff',arrowsize=15)
    s.configure('Treeview',rowheight=30)
    return font
