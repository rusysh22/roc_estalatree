"""Shared formatting helpers (money, dates)."""


def format_rupiah(value, *, signed: bool = False) -> str:
    """Format an integer rupiah value with dot-grouped thousands.

    Examples:
        1000        -> "Rp1.000"
        -99000      -> "-Rp99.000"
        100000      -> "Rp100.000"
        100000 (+)  -> "+Rp100.000"
    """
    v = int(value or 0)
    grouped = f"{abs(v):,}".replace(",", ".")
    if v < 0:
        sign = "-"
    elif signed and v > 0:
        sign = "+"
    else:
        sign = ""
    return f"{sign}Rp{grouped}"
