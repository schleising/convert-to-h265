# Start with the Linuxserver ffmpeg image as the build image
FROM linuxserver/ffmpeg:7.0.1 AS build

# Add Python and Pip
RUN apt update && apt upgrade -y && apt install -y git python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Add the required packages, disabling cache to reduce the size of the image
COPY ./requirements.txt /requirements.txt
RUN pip install --user --no-cache-dir --break-system-packages -r /requirements.txt

# Create a new image with the required packages
FROM linuxserver/ffmpeg:7.0.1

# Install Python 3 Minimal
RUN apt update && apt upgrade -y && apt install -y python3-minimal && rm -rf /var/lib/apt/lists/*

# Copy the required packages from the build image
COPY --from=build /root/.local /root/.local

# Set the entrypoint to run uvicorn with a socket connection
ENTRYPOINT [ "python3",  "/src/main.py"]
