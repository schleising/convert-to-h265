from datetime import datetime, UTC


def calculate_time_remaining(start_time: datetime | None, progress: float) -> str:
    """Calculate the time remaining for a conversion.

    Args:
        start_time (datetime | None): The start time of the conversion.
        progress (float): The percentage complete of the conversion.

    Returns:
        str: The time remaining for the conversion.
    """
    # Calculate the time remaining
    if progress != 0 and start_time is not None:
        time_remaining = (datetime.now().astimezone(UTC) - start_time) / progress * (100 - progress)
        time_string = str(time_remaining).split('.')[0]
    else:
        time_string = 'Calculating...'

    # Return the time remaining
    return time_string
