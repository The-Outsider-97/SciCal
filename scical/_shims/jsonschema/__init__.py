"""A stand-in for jsonschema (see ../README.md). SLAI's planning module imports it when it loads, but the STEM agent never validates a schema.
Using it for validation raises a clear error instead of pretending to validate."""
__version__ = "0+scical-shim"


class ValidationError(Exception):
    pass


class Draft202012Validator:
    def __init__(self, schema):
        raise RuntimeError("jsonschema is not installed on this device, so JSON-schema validation is unavailable")

    @classmethod
    def check_schema(cls, schema):
        raise RuntimeError("jsonschema is not installed on this device, so JSON-schema validation is unavailable")
