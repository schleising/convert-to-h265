from pathlib import Path
import argparse

class SMBDelete:
    def __init__(self, delete=False):
        self.delete = delete
        self.temp_file_size = 0

    def find_smbdelete(self, filepath: Path) -> None:
        for file in filepath.iterdir():
            if file.is_dir():
                self.find_smbdelete(file)
            elif file.name.startswith('.smbdelete'):
                size = file.stat().st_size
                self.temp_file_size += size
                print(f'{file} - {self.sizeof_fmt(size)} - {self.sizeof_fmt(self.temp_file_size)}')

                if self.delete:
                    try:
                        file.unlink()
                        print(f'Deleted {file}')
                    except OSError as e:
                        print(f'Error: {e.filename} - {e.strerror}')

    def sizeof_fmt(self, num, suffix="B"):
        for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
            if abs(num) < 1024.0:
                return f"{num:3.3f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}Yi{suffix}"

if __name__ == '__main__':
    # Add an argument to delete the files
    parser = argparse.ArgumentParser(description='Find and optionally delete .smbdelete files.')
    parser.add_argument('--delete', '-d', action='store_true', default=False)
    args = parser.parse_args()

    if args.delete:
        print('Delete mode enabled')
    else:
        print('Delete mode disabled')

    tv_filepath = Path('/volume2/Media/TV')
    film_filepath = Path('/volume2/Media/Films')
    backup_filepath = Path('/volume2/Media/Backup')
    recycle_filepath = Path('/volume2/Media/#recycle')

    smb_delete = SMBDelete(args.delete)

    smb_delete.find_smbdelete(tv_filepath)
    smb_delete.find_smbdelete(film_filepath)
    smb_delete.find_smbdelete(backup_filepath)
    smb_delete.find_smbdelete(recycle_filepath)
