# Start with the Linuxserver ffmpeg image as the build image
FROM linuxserver/ffmpeg:latest AS build

# Add Python and Pip
RUN apt update && apt upgrade -y && apt install -y git python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Install packages to a prefix so any non-root UID can use them
COPY ./requirements.txt /requirements.txt
RUN pip install --no-cache-dir --break-system-packages --prefix=/install -r /requirements.txt

# Create a new image with the required packages
FROM linuxserver/ffmpeg:latest

# Install Python 3 Minimal and create a non-root user matching the macOS host
# (uid 501 / gid 20). Reuse the existing dialout group instead of creating gid 20.
RUN apt update && apt upgrade -y && apt install -y python3-minimal \
    && useradd --uid 501 --gid 20 --create-home --home-dir /home/app app \
    && rm -rf /var/lib/apt/lists/*

# Debian pip places files under <prefix>/local; merge into /usr/local
COPY --from=build /install/local/ /usr/local/

ENV HOME=/home/app \
    PATH=/usr/local/bin:$PATH

USER app

# Set the entrypoint to run the converter
ENTRYPOINT [ "python3",  "/src/main.py"]
