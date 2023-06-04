import logging
import sys
import signal

from converter import TaskScheduler

def signal_handler(sig: int, _):
    # Handle SIGINT and SIGTERM signals to ensure the Docker container stops gracefully
    match sig:
        case signal.SIGINT:
            logging.info("Stopping due to keyboard interrupt...")
            sys.exit(0)
        case signal.SIGTERM:
            logging.info("Stopping due to SIGTERM...")
            sys.exit(0)

def main() -> None:
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create the task scheduler
    scheduler = TaskScheduler()

    # Run the task scheduler
    scheduler.run()

if __name__ == "__main__":
    # Run the main function
    main()
