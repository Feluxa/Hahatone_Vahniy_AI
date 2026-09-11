def contains(value: int, start: int, end: int) -> bool:
    if start > end:
        raise ValueError("start must not exceed end")
    return start <= value <= end
