#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from gui import main as gui

gui.seed_all_defaults()
app = gui.App()
app.mainloop()
