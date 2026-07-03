def test_gui_module_exposes_entry_points():
    import e32config.gui as gui

    assert callable(gui.run)
    assert hasattr(gui, "E32Gui")
