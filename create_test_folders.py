from pathlib import Path


def main() -> None:
    # Get the user's Downloads directory
    downloads = Path.home() / "Downloads"

    # Define the directories to be created
    directories = [
        downloads / "Media",
        downloads / "Media" / "Films",
        downloads / "Media" / "TV",
        downloads / "Media" / "Backup",
    ]

    # Create the directories
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"Created {directory}")


if __name__ == "__main__":
    main()
