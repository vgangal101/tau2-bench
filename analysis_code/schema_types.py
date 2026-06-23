import re


def annotation_to_str(annotation) -> str:
    """Normalize a type annotation to a comparable canonical string.

    Strips module qualifiers and the ``typing.`` prefix so that the same type
    compares equal whether it comes from a live entity field
    (``tau2.domains.airline.data_model.Passenger``) or a stored schema string
    (``Passenger``). Examples:
        <class 'str'>                                  -> "str"
        typing.Optional[typing.Literal['cancelled']]   -> "Optional[Literal['cancelled']]"
        typing.List[...data_model.Passenger]           -> "List[Passenger]"
    """
    if isinstance(annotation, type):
        return annotation.__name__
    s = str(annotation)
    s = s.replace("typing.", "")
    # Collapse dotted module paths (e.g. a.b.c.Passenger) to the bare name.
    s = re.sub(r"(?:[A-Za-z_]\w*\.)+(\w+)", r"\1", s)
    return s
