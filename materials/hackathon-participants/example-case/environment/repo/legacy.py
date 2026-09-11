def contains_closed(value: int, start: int, end: int) -> bool:
    """Проверка закрытого интервала для существующих клиентов."""
    if start > end:
        raise ValueError("start must not exceed end")
    return start <= value <= end
