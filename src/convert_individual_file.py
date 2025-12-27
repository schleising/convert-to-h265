import os
import sys

os.environ["DB_URL"] = "mongodb://macmini2.home.arpa:27017"
os.environ["DB_NAME"] = "media"
os.environ["DB_COLLECTION"] = "media_collection"
os.environ["PUSH_COLLECTION"] = "push_subscriptions"

from converter.models import FileData
from converter import media_collection


def main(restore: bool) -> None:
    if restore:
        print("Restoring file info from file_info_db.json")

        with open("tests/file_info_db.json", "r") as f:
            file_info_db = FileData.model_validate_json(f.read())

        media_collection.find_one_and_update(
            {"filename": file_info_db.filename}, {"$set": file_info_db.model_dump()}
        )
    else:
        with open("tests/filename.txt", "r") as f:
            filename = f.read().strip()

        file_info_db = media_collection.find_one_and_update(
            {
                "filename": filename,
            },
            {"$set": {"converted": False}},
        )

        with open("tests/file_info_db.json", "w") as f:
            f.write(FileData.model_validate(file_info_db).model_dump_json(indent=2))


if __name__ == "__main__":
    # Parse the command line arguments
    restore = sys.argv[1] == "-r" if len(sys.argv) > 1 else False

    main(restore=restore)
