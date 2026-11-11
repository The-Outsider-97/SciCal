Stand-ins for two third-party packages, used only where the real ones are not installed (the Android app, whose Python has no SciPy or
jsonschema wheels). They sit at the END of `sys.path`, so a real installation always wins. Each does only what SLAI's STEM agent calls.
