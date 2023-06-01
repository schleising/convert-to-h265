from pathlib import Path
from converter.walk_folders import WalkFolders

if __name__ == "__main__":
    walker = WalkFolders(path=Path('/volumes/Media/TV'))

    walker.walk()
    walker.get_file_encoding()
    walker.print_files()
