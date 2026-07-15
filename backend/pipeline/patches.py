"""openpyxl monkey-patch for malformed aRGB color values in EXIM files.
MUST be imported before openpyxl workbooks are loaded anywhere in the app."""
import openpyxl.styles.colors as _opc

_orig_rgb_set = _opc.RGB.__set__

def _patched_rgb_set(self, instance, value):
    try:
        _orig_rgb_set(self, instance, value)
    except ValueError:
        instance.__dict__[self.name] = '00000000'

_opc.RGB.__set__ = _patched_rgb_set
