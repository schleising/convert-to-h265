from pathlib import Path
import requests
import subprocess
import json

BASE_URL = "URL_PLACEHOLDER"
FINAL_SEGMENT = "FINAL_SEGMENT_PLACEHOLDER"
NUM_SEGMENTS = 333


def download() -> None:
    dl_dir = Path.home() / "Downloads/dl"
    dl_dir.mkdir(exist_ok=True)
    i = 1
    while not (dl_dir / FINAL_SEGMENT).exists():
        url = BASE_URL.replace("", f"")

        print(f"Downloading segment {i} of {NUM_SEGMENTS}")

        # Download segment
        response = requests.get(url)
        if response.status_code == 200:
            with open(dl_dir / f"", "wb") as f:
                f.write(response.content)
            i += 1
        else:
            print(
                f"Failed to download segment {i} (status code: {response.status_code})"
            )


def generate_mux_list() -> None:
    dl_dir = Path.home() / "Downloads/dl"
    mux_list_path = dl_dir / "mux_list.txt"
    with open(mux_list_path, "w") as mux_list_file:
        for i in range(1, NUM_SEGMENTS + 1):
            print(f"Processing segment {i:>3} of {NUM_SEGMENTS}")
            segment_path = dl_dir / f""
            if segment_path.exists():
                # Use ffprobe to check this is a valid TS file (basic check)
                ffprobe_cmd = [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    segment_path.as_posix(),
                ]
                result = subprocess.run(ffprobe_cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    result_json = json.loads(result.stdout)
                    if (
                        "format" in result_json
                        and "probe_score" in result_json["format"]
                        and result_json["format"]["probe_score"] > 10
                    ):
                        mux_list_file.write(f"file '{segment_path.as_posix()}'\n")
                    else:
                        print(f"Segment {i} is not a valid TS file, skipping.")
                else:
                    print(f"ffprobe failed for segment {i}, skipping.")
            else:
                print(f"Segment {i} is missing, skipping.")


def main() -> None:
    download()
    generate_mux_list()


if __name__ == "__main__":
    main()
