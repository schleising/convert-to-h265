# Start with the Linuxserver ffmpeg image as the build image
FROM linuxserver/ffmpeg:latest

# Add Python and Pip
RUN apt update && apt upgrade -y && apt install -y python3 python3-pip

# Add the required packages, disabling cache to reduce the size of the image
COPY ./requirements.txt /requirements.txt
RUN pip install --user --no-cache-dir -r /requirements.txt

# Set the entrypoint to run uvicorn with a socket connection
ENTRYPOINT [ "python3",  "/src/main.py"]
