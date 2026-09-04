#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from gui.main import App
App().mainloop()